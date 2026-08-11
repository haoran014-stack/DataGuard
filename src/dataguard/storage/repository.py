"""SQLAlchemy audit repository with deterministic cursor pagination."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError
from sqlalchemy import Engine, and_, create_engine, event as sqlalchemy_event, inspect, insert, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from dataguard.config import RuntimeSettings, StorageBackend
from .errors import AuditQueryError, StorageError
from .models import AuditEvent, AuditEventFilter, AuditEventPage
from .paths import SafeSQLiteLocation
from .schema import (
    audit_authorization_denials, audit_detections, audit_events,
    audit_retrieved_documents, metadata,
)

_CURSOR_VERSION = 1
_MAX_CURSOR_BYTES = 512
_REPOSITORY_TOKEN = object()


class AuditRepository(Protocol):
    def prepare_schema(self) -> None: ...
    def append_event(self, audit_event: AuditEvent) -> None: ...
    def list_events(self, filters: AuditEventFilter) -> AuditEventPage: ...
    def healthcheck(self) -> bool: ...
    def close(self) -> None: ...


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _encode_cursor(occurred_at: str, event_id: str) -> str:
    core = {"event_id": event_id, "occurred_at": occurred_at, "version": _CURSOR_VERSION}
    core_bytes = json.dumps(core, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload = {**core, "checksum": hashlib.sha256(core_bytes).hexdigest()}
    raw = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate")
        result[key] = value
    return result


def _decode_cursor(value: str) -> tuple[str, str]:
    try:
        if type(value) is not str or not value or len(value) > _MAX_CURSOR_BYTES or "=" in value:
            raise ValueError("cursor")
        padding = "=" * ((4 - len(value) % 4) % 4)
        raw = base64.b64decode(value + padding, altchars=b"-_", validate=True)
        if len(raw) > _MAX_CURSOR_BYTES:
            raise ValueError("cursor")
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_duplicate_pairs)
        if type(payload) is not dict or set(payload) != {"checksum", "event_id", "occurred_at", "version"}:
            raise ValueError("cursor")
        if (payload["version"] != _CURSOR_VERSION or type(payload["event_id"]) is not str
                or type(payload["occurred_at"]) is not str or type(payload["checksum"]) is not str
                or len(payload["checksum"]) != 64
                or any(character not in "0123456789abcdef" for character in payload["checksum"])):
            raise ValueError("cursor")
        core = {"event_id": payload["event_id"], "occurred_at": payload["occurred_at"], "version": _CURSOR_VERSION}
        core_bytes = json.dumps(core, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if not hmac.compare_digest(payload["checksum"], hashlib.sha256(core_bytes).hexdigest()):
            raise ValueError("cursor")
        if base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != value:
            raise ValueError("cursor")
        # Reuse public validators without exposing input on failure.
        probe = AuditEventFilter.model_validate({"cursor": value})
        del probe
        parsed_timestamp = datetime.fromisoformat(payload["occurred_at"].replace("Z", "+00:00"))
        if parsed_timestamp.tzinfo is None or _timestamp(parsed_timestamp) != payload["occurred_at"]:
            raise ValueError("cursor")
        from uuid import UUID
        if str(UUID(payload["event_id"])) != payload["event_id"]:
            raise ValueError("cursor")
        return payload["occurred_at"], payload["event_id"]
    except (ValueError, TypeError, UnicodeError, json.JSONDecodeError, ValidationError):
        raise AuditQueryError() from None


class SQLAlchemyAuditRepository:
    """Thread-safe local repository; its constructor performs no connection or file I/O."""

    __slots__ = ("_backend", "_closed", "_engine", "_lock", "_sqlite_location")

    def __init__(self, backend: StorageBackend, engine: Engine,
                 sqlite_location: SafeSQLiteLocation | None, *, _token: object | None = None) -> None:
        if _token is not _REPOSITORY_TOKEN:
            raise StorageError()
        self._backend = backend
        self._engine = engine
        self._sqlite_location = sqlite_location
        self._lock = threading.RLock()
        self._closed = False

    def __repr__(self) -> str:
        return f"SQLAlchemyAuditRepository(backend='{self._backend.value}')"

    def _require_open(self) -> None:
        if self._closed:
            raise StorageError()

    def _validate_runtime_storage(self) -> None:
        if self._sqlite_location is not None:
            self._sqlite_location.validate_parent_chain()
            self._sqlite_location.validate_target(allow_missing=False)

    @staticmethod
    def _validate_schema(connection: Any) -> None:
        inspector = inspect(connection)
        expected = {table.name: set(table.c.keys()) for table in metadata.tables.values()}
        actual_names = set(inspector.get_table_names())
        if actual_names != set(expected):
            raise StorageError()
        for table_name, expected_columns in expected.items():
            actual_columns = {item["name"] for item in inspector.get_columns(table_name)}
            if actual_columns != expected_columns:
                raise StorageError()

    def prepare_schema(self) -> None:
        with self._lock:
            self._require_open()
            try:
                if self._sqlite_location is not None:
                    self._sqlite_location.prepare_parent()
                metadata.create_all(self._engine)
                with self._engine.connect() as connection:
                    self._validate_schema(connection)
                if self._sqlite_location is not None:
                    self._sqlite_location.prepare_parent()
                    self._sqlite_location.validate_target(allow_missing=False)
            except StorageError:
                raise
            except Exception:
                raise StorageError() from None

    def append_event(self, audit_event: AuditEvent) -> None:
        try:
            if type(audit_event) is not AuditEvent:
                raise TypeError("invalid event")
            safe = AuditEvent.model_validate(audit_event.model_dump(mode="python"))
        except Exception:
            raise StorageError() from None
        main = safe.model_dump(mode="json", exclude={"retrieved_documents", "authorization_denials", "detections"})
        main["occurred_at"] = _timestamp(safe.occurred_at)
        with self._lock:
            self._require_open()
            try:
                self._validate_runtime_storage()
                with self._engine.begin() as connection:
                    self._validate_schema(connection)
                    connection.execute(insert(audit_events).values(**main))
                    if safe.retrieved_documents:
                        connection.execute(insert(audit_retrieved_documents), [
                            {"event_id": safe.event_id, "position": position, **item.model_dump(mode="json")}
                            for position, item in enumerate(safe.retrieved_documents)
                        ])
                    if safe.authorization_denials:
                        connection.execute(insert(audit_authorization_denials), [
                            {"event_id": safe.event_id, "position": position, **item.model_dump(mode="json")}
                            for position, item in enumerate(safe.authorization_denials)
                        ])
                    if safe.detections:
                        connection.execute(insert(audit_detections), [
                            {"event_id": safe.event_id, "position": position, **item.model_dump(mode="json")}
                            for position, item in enumerate(safe.detections)
                        ])
            except StorageError:
                raise
            except Exception:
                raise StorageError() from None

    def _hydrate(self, connection: Any, row: Mapping[str, Any]) -> AuditEvent:
        event_id = row["event_id"]
        retrieved = connection.execute(select(audit_retrieved_documents).where(audit_retrieved_documents.c.event_id == event_id).order_by(audit_retrieved_documents.c.position)).mappings().all()
        denials = connection.execute(select(audit_authorization_denials).where(audit_authorization_denials.c.event_id == event_id).order_by(audit_authorization_denials.c.position)).mappings().all()
        detections = connection.execute(select(audit_detections).where(audit_detections.c.event_id == event_id).order_by(audit_detections.c.position)).mappings().all()
        value = dict(row)
        value["occurred_at"] = datetime.fromisoformat(value["occurred_at"].replace("Z", "+00:00"))
        value["retrieved_documents"] = [{k: v for k, v in item.items() if k not in {"event_id", "position"}} for item in retrieved]
        value["authorization_denials"] = [{k: v for k, v in item.items() if k not in {"event_id", "position"}} for item in denials]
        value["detections"] = [{k: v for k, v in item.items() if k not in {"event_id", "position"}} for item in detections]
        return AuditEvent.model_validate(value)

    def list_events(self, filters: AuditEventFilter) -> AuditEventPage:
        try:
            if type(filters) is not AuditEventFilter:
                raise TypeError("invalid filters")
            safe_filters = AuditEventFilter.model_validate(filters.model_dump(mode="python"))
        except Exception:
            raise AuditQueryError() from None
        cursor_key = _decode_cursor(safe_filters.cursor) if safe_filters.cursor is not None else None
        clauses = []
        for name in ("trace_id", "run_id", "subject_id", "mode", "event_type"):
            value = getattr(safe_filters, name)
            if value is not None:
                clauses.append(audit_events.c[name] == (value.value if hasattr(value, "value") else value))
        if safe_filters.start_time is not None:
            clauses.append(audit_events.c.occurred_at >= _timestamp(safe_filters.start_time))
        if safe_filters.end_time is not None:
            clauses.append(audit_events.c.occurred_at <= _timestamp(safe_filters.end_time))
        if cursor_key is not None:
            timestamp, event_id = cursor_key
            clauses.append((audit_events.c.occurred_at > timestamp) | and_(audit_events.c.occurred_at == timestamp, audit_events.c.event_id > event_id))
        statement = select(audit_events).order_by(audit_events.c.occurred_at, audit_events.c.event_id).limit(safe_filters.limit + 1)
        if clauses:
            statement = statement.where(and_(*clauses))
        with self._lock:
            self._require_open()
            try:
                self._validate_runtime_storage()
                with self._engine.connect() as connection:
                    self._validate_schema(connection)
                    rows = connection.execute(statement).mappings().all()
                    hydrated = tuple(self._hydrate(connection, row) for row in rows[:safe_filters.limit])
            except StorageError:
                raise
            except Exception:
                raise StorageError() from None
        next_cursor = None
        if len(rows) > safe_filters.limit:
            last = rows[safe_filters.limit - 1]
            next_cursor = _encode_cursor(last["occurred_at"], last["event_id"])
        return AuditEventPage(items=hydrated, next_cursor=next_cursor)

    def healthcheck(self) -> bool:
        with self._lock:
            self._require_open()
            try:
                self._validate_runtime_storage()
                with self._engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                    self._validate_schema(connection)
                return True
            except StorageError:
                raise
            except Exception:
                raise StorageError() from None

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                try:
                    self._engine.dispose()
                except Exception:
                    raise StorageError() from None
                finally:
                    self._closed = True


def create_audit_repository(settings: RuntimeSettings, project_root: Path) -> SQLAlchemyAuditRepository:
    """Create a lazy repository without connecting or touching the filesystem."""

    try:
        if type(settings) is not RuntimeSettings:
            raise StorageError()
        safe = RuntimeSettings.model_validate({
            **settings.model_dump(mode="python"),
            "database_dsn": settings.database_dsn_value(),
        })
        if safe.storage_backend is StorageBackend.SQLITE:
            location = SafeSQLiteLocation.from_settings(project_root, safe)
            url = URL.create("sqlite+pysqlite", database=str(location.target))
            engine = create_engine(url, hide_parameters=True, connect_args={"check_same_thread": False})

            @sqlalchemy_event.listens_for(engine, "connect")
            def _sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("PRAGMA foreign_keys=ON")
                finally:
                    cursor.close()
        else:
            location = None
            engine = create_engine(safe.database_dsn_value(), hide_parameters=True)
        return SQLAlchemyAuditRepository(safe.storage_backend, engine, location, _token=_REPOSITORY_TOKEN)
    except StorageError:
        raise
    except Exception:
        raise StorageError() from None
