"""SQLAlchemy audit repository with deterministic cursor pagination."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import Engine, and_, create_engine, event as sqlalchemy_event, inspect, insert, select, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from dataguard.config import RuntimeSettings, StorageBackend
from .errors import (
    AuditQueryError, ReportNotReadyError, ReportUnavailableError,
    ReportValidationError, RunNotFoundError, RunStateError, StorageError,
)
from .models import (
    AuditEvent, AuditEventFilter, AuditEventPage, ErrorCode, EvaluationProfile,
    EvaluationRun, RunStatus, StoredReport,
)
from .paths import SafeSQLiteLocation
from .reporting import load_report_validator, validate_and_canonicalize_report
from .schema import (
    audit_authorization_denials, audit_detections, audit_events,
    audit_retrieved_documents, evaluation_reports, evaluation_runs, metadata,
)

_CURSOR_VERSION = 1
_MAX_CURSOR_BYTES = 512
_REPOSITORY_TOKEN = object()


class AuditRepository(Protocol):
    def prepare_schema(self) -> None: ...
    def append_event(self, audit_event: AuditEvent) -> None: ...
    def list_events(self, filters: AuditEventFilter) -> AuditEventPage: ...
    def create_run(self, scenario_set_version: str, profile: EvaluationProfile,
                   created_at: datetime) -> EvaluationRun: ...
    def get_run(self, run_id: str) -> EvaluationRun: ...
    def list_queued_runs(self) -> tuple[EvaluationRun, ...]: ...
    def get_report(self, run_id: str) -> StoredReport: ...
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

    __slots__ = ("_backend", "_closed", "_engine", "_lock", "_project_root",
                 "_report_validator", "_sqlite_location")

    def __init__(self, backend: StorageBackend, engine: Engine,
                 sqlite_location: SafeSQLiteLocation | None, project_root: Path | None = None,
                 *, _token: object | None = None) -> None:
        if _token is not _REPOSITORY_TOKEN:
            raise StorageError()
        if project_root is None:
            raise StorageError()
        self._backend = backend
        self._engine = engine
        self._sqlite_location = sqlite_location
        self._project_root = project_root
        self._report_validator = None
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
                    self._sqlite_location.validate_project_root()
                validator = self._report_validator
                if validator is None:
                    validator = load_report_validator(self._project_root)
                if self._sqlite_location is not None:
                    self._sqlite_location.prepare_parent()
                metadata.create_all(self._engine)
                with self._engine.connect() as connection:
                    self._validate_schema(connection)
                if self._sqlite_location is not None:
                    self._sqlite_location.prepare_parent()
                    self._sqlite_location.validate_target(allow_missing=False)
                self._report_validator = validator
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

    @staticmethod
    def _hydrate_run(row: Mapping[str, Any]) -> EvaluationRun:
        value = dict(row)
        for name in ("created_at", "updated_at", "completed_at"):
            if value[name] is not None:
                value[name] = datetime.fromisoformat(value[name].replace("Z", "+00:00"))
        return EvaluationRun.model_validate(value)

    @staticmethod
    def _run_id(run_id: str) -> str:
        try:
            if type(run_id) is not str or str(UUID(run_id)) != run_id:
                raise ValueError("run identifier")
            return run_id
        except Exception:
            raise RunNotFoundError() from None

    @staticmethod
    def _run_time(value: datetime) -> datetime:
        try:
            if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("run time")
            return value.astimezone(timezone.utc)
        except Exception:
            raise RunStateError() from None

    def _fetch_run(self, connection: Any, run_id: str, *, lock: bool = False) -> EvaluationRun:
        statement = select(evaluation_runs).where(evaluation_runs.c.run_id == run_id)
        if lock:
            statement = statement.with_for_update()
        row = connection.execute(statement).mappings().one_or_none()
        if row is None:
            raise RunNotFoundError()
        run = self._hydrate_run(row)
        reports = connection.execute(select(evaluation_reports.c.run_id).where(
            evaluation_reports.c.run_id == run_id)).all()
        if len(reports) != (1 if run.status is RunStatus.COMPLETED else 0):
            raise StorageError()
        return run

    def create_run(self, scenario_set_version: str, profile: EvaluationProfile,
                   created_at: datetime) -> EvaluationRun:
        from uuid import uuid4
        try:
            if type(profile) is not EvaluationProfile:
                raise TypeError("profile")
            if profile is EvaluationProfile.EVIDENCE and self._backend is not StorageBackend.POSTGRESQL:
                raise ValueError("evidence storage")
            run = EvaluationRun(run_id=str(uuid4()), status=RunStatus.QUEUED,
                scenario_set_version=scenario_set_version, profile=profile,
                completed_scenarios=0, total_scenarios=62, created_at=created_at,
                updated_at=created_at, completed_at=None, failure_code=None)
        except Exception:
            raise RunStateError() from None
        values = run.model_dump(mode="json")
        values["created_at"] = _timestamp(run.created_at)
        values["updated_at"] = _timestamp(run.updated_at)
        with self._lock:
            self._require_open()
            try:
                self._validate_runtime_storage()
                with self._engine.begin() as connection:
                    self._validate_schema(connection)
                    connection.execute(insert(evaluation_runs).values(**values))
                return run
            except StorageError:
                raise
            except Exception:
                raise StorageError() from None

    def get_run(self, run_id: str) -> EvaluationRun:
        safe_id = self._run_id(run_id)
        with self._lock:
            self._require_open()
            try:
                self._validate_runtime_storage()
                with self._engine.connect() as connection:
                    self._validate_schema(connection)
                    return self._fetch_run(connection, safe_id)
            except (RunNotFoundError, StorageError):
                raise
            except Exception:
                raise StorageError() from None

    def list_queued_runs(self) -> tuple[EvaluationRun, ...]:
        """Return persisted queued runs in deterministic FIFO order."""

        with self._lock:
            self._require_open()
            try:
                self._validate_runtime_storage()
                with self._engine.connect() as connection:
                    self._validate_schema(connection)
                    rows = connection.execute(
                        select(evaluation_runs)
                        .where(evaluation_runs.c.status == RunStatus.QUEUED.value)
                        .order_by(evaluation_runs.c.created_at, evaluation_runs.c.run_id)
                    ).mappings().all()
                    return tuple(self._hydrate_run(row) for row in rows)
            except StorageError:
                raise
            except Exception:
                raise StorageError() from None

    def _transition(self, run_id: str, updated_at: datetime, action: str,
                    failure_code: ErrorCode | None = None) -> EvaluationRun:
        safe_id = self._run_id(run_id)
        moment = self._run_time(updated_at)
        with self._lock:
            self._require_open()
            try:
                self._validate_runtime_storage()
                with self._engine.begin() as connection:
                    self._validate_schema(connection)
                    current = self._fetch_run(connection, safe_id, lock=True)
                    if moment < current.updated_at:
                        raise RunStateError()
                    if action == "start" and current.status is RunStatus.QUEUED:
                        values = {"status": RunStatus.RUNNING.value, "updated_at": _timestamp(moment)}
                    elif action == "advance" and current.status is RunStatus.RUNNING and current.completed_scenarios < 61:
                        values = {"completed_scenarios": current.completed_scenarios + 1,
                                  "updated_at": _timestamp(moment)}
                    elif action == "fail" and current.status is RunStatus.RUNNING and type(failure_code) is ErrorCode:
                        values = {"status": RunStatus.FAILED.value, "failure_code": failure_code.value,
                                  "updated_at": _timestamp(moment)}
                    else:
                        raise RunStateError()
                    connection.execute(evaluation_runs.update().where(
                        evaluation_runs.c.run_id == safe_id).values(**values))
                    return self._fetch_run(connection, safe_id)
            except (RunNotFoundError, RunStateError, StorageError):
                raise
            except Exception:
                raise StorageError() from None

    def start_run(self, run_id: str, updated_at: datetime) -> EvaluationRun:
        return self._transition(run_id, updated_at, "start")

    def advance_run(self, run_id: str, updated_at: datetime) -> EvaluationRun:
        return self._transition(run_id, updated_at, "advance")

    def fail_run(self, run_id: str, failure_code: ErrorCode,
                 updated_at: datetime) -> EvaluationRun:
        return self._transition(run_id, updated_at, "fail", failure_code)

    def recover_interrupted_runs(self, recovered_at: datetime) -> int:
        moment = self._run_time(recovered_at)
        with self._lock:
            self._require_open()
            try:
                self._validate_runtime_storage()
                with self._engine.begin() as connection:
                    self._validate_schema(connection)
                    rows = connection.execute(select(evaluation_runs).where(
                        evaluation_runs.c.status == RunStatus.RUNNING.value).with_for_update()).mappings().all()
                    runs = tuple(self._hydrate_run(row) for row in rows)
                    if any(moment < run.updated_at for run in runs):
                        raise RunStateError()
                    if rows:
                        run_ids = tuple(run.run_id for run in runs)
                        if connection.execute(select(evaluation_reports.c.run_id).where(
                                evaluation_reports.c.run_id.in_(run_ids))).first() is not None:
                            raise StorageError()
                        connection.execute(evaluation_runs.update().where(
                            evaluation_runs.c.status == RunStatus.RUNNING.value).values(
                                status=RunStatus.INTERRUPTED.value,
                                failure_code=ErrorCode.INTERNAL_ERROR.value,
                                updated_at=_timestamp(moment)))
                    return len(rows)
            except (RunStateError, StorageError):
                raise
            except Exception:
                raise StorageError() from None

    def complete_run(self, run_id: str, report: Mapping[str, Any],
                     completed_at: datetime) -> EvaluationRun:
        safe_id = self._run_id(run_id)
        moment = self._run_time(completed_at)
        validator = self._report_validator
        if validator is None:
            raise StorageError()
        with self._lock:
            self._require_open()
            try:
                self._validate_runtime_storage()
                with self._engine.begin() as connection:
                    self._validate_schema(connection)
                    current = self._fetch_run(connection, safe_id, lock=True)
                    if (current.status is not RunStatus.RUNNING
                            or current.completed_scenarios != 61
                            or moment < current.updated_at):
                        raise RunStateError()
                    safe, canonical, digest = validate_and_canonicalize_report(
                        report, expected_run_id=safe_id,
                        expected_profile=current.profile.value,
                        expected_scenario_set_version=current.scenario_set_version,
                        expected_storage_backend=self._backend.value,
                        expected_generated_at=moment, validator=validator)
                    generated_at = datetime.fromisoformat(safe["generated_at"].replace("Z", "+00:00"))
                    stored = StoredReport(run_id=safe_id, report_id=safe["report_id"],
                        generated_at=generated_at, sha256=digest, canonical_json=canonical)
                    connection.execute(insert(evaluation_reports).values(
                        run_id=safe_id, report_id=stored.report_id,
                        generated_at=_timestamp(stored.generated_at),
                        canonical_json=canonical.decode("utf-8"), sha256=digest))
                    connection.execute(evaluation_runs.update().where(
                        evaluation_runs.c.run_id == safe_id).values(
                            status=RunStatus.COMPLETED.value, completed_scenarios=62,
                            updated_at=_timestamp(moment), completed_at=_timestamp(moment),
                            failure_code=None))
                    return self._fetch_run(connection, safe_id)
            except (ReportValidationError, RunNotFoundError, RunStateError, StorageError):
                raise
            except Exception:
                raise StorageError() from None

    def get_report(self, run_id: str) -> StoredReport:
        safe_id = self._run_id(run_id)
        with self._lock:
            self._require_open()
            try:
                self._validate_runtime_storage()
                with self._engine.connect() as connection:
                    self._validate_schema(connection)
                    run = self._fetch_run(connection, safe_id)
                    if run.status in {RunStatus.QUEUED, RunStatus.RUNNING}:
                        raise ReportNotReadyError()
                    if run.status in {RunStatus.FAILED, RunStatus.INTERRUPTED}:
                        raise ReportUnavailableError()
                    validator = self._report_validator
                    if validator is None:
                        raise StorageError()
                    row = connection.execute(select(evaluation_reports).where(
                        evaluation_reports.c.run_id == safe_id)).mappings().one()
                    canonical = row["canonical_json"].encode("utf-8")
                    safe, exact, digest = validate_and_canonicalize_report(
                        json.loads(canonical), expected_run_id=safe_id,
                        expected_profile=run.profile.value,
                        expected_scenario_set_version=run.scenario_set_version,
                        expected_storage_backend=self._backend.value,
                        expected_generated_at=run.completed_at, validator=validator)
                    if (canonical != exact or digest != row["sha256"]
                            or safe["report_id"] != row["report_id"]
                            or _timestamp(datetime.fromisoformat(safe["generated_at"].replace("Z", "+00:00"))) != row["generated_at"]):
                        raise StorageError()
                    return StoredReport(run_id=safe_id, report_id=row["report_id"],
                        generated_at=datetime.fromisoformat(row["generated_at"].replace("Z", "+00:00")),
                        sha256=digest, canonical_json=canonical)
            except (ReportNotReadyError, ReportUnavailableError, RunNotFoundError, StorageError):
                raise
            except ReportValidationError:
                raise StorageError() from None
            except Exception:
                raise StorageError() from None

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
        if not isinstance(project_root, Path) or not project_root.is_absolute():
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
        root = Path(os.path.abspath(project_root))
        return SQLAlchemyAuditRepository(safe.storage_backend, engine, location, root,
                                         _token=_REPOSITORY_TOKEN)
    except StorageError:
        raise
    except Exception:
        raise StorageError() from None
