from __future__ import annotations

import base64
import json
import os
import hashlib
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event as sqlalchemy_event, inspect, insert, text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateTable

from dataguard.config import RuntimeSettings, StorageBackend
from dataguard.detector.models import DetectionAction, DetectionType
from dataguard.domain.models import Role
from dataguard.rag.models import RagMode
from dataguard.storage import (
    AuditDetectorAction, AuditEvent, AuditEventFilter, AuditEventType, AuditOutcome,
    AuditQueryError, AuthorizationDenial, DetectionEvidence, RetrievedDocumentEvidence,
    StorageError, create_audit_repository, metadata,
)
from dataguard.storage.paths import _REPARSE_ATTRIBUTE
from dataguard.storage.schema import audit_detections, audit_events

RAW = "RAW-AUDIT-SENTINEL"
UTC = timezone.utc


def event_at(moment: datetime, *, event_id: str | None = None, subject: str = "guest-01") -> AuditEvent:
    return AuditEvent(
        event_id=event_id or str(uuid4()), event_type=AuditEventType.CHAT_COMPLETED,
        occurred_at=moment, trace_id=str(uuid4()), run_id=str(uuid4()), subject_id=subject,
        resolved_role=Role.GUEST, mode=RagMode.BASELINE, outcome=AuditOutcome.ANSWERED,
        corpus_version="synthetic-v1",
        retrieved_documents=(RetrievedDocumentEvidence(document_id="doc-public-01", rank=1,
            similarity_score=0.75, authorized=True, included_in_context=True, denial_reason=None),),
        authorization_denials=(AuthorizationDenial(document_id="doc-internal-01", reason="role_not_allowed"),),
        detections=(DetectionEvidence(type=DetectionType.DOCUMENT_CANARY, evidence_id="canary-01",
            violation=True, action=DetectionAction.OBSERVED),),
    )


@pytest.fixture
def repository(tmp_path: Path):
    settings = RuntimeSettings()
    repo = create_audit_repository(settings, tmp_path)
    repo.prepare_schema()
    yield repo
    repo.close()


def test_models_recompute_counts_and_reject_drift() -> None:
    item = event_at(datetime.now(UTC))
    assert item.retrieved_document_count == 1
    assert item.unauthorized_context_count == 0
    assert item.canary_match_count == 1
    assert item.protected_fragment_match_count == 0
    assert item.detector_action is AuditDetectorAction.OBSERVED
    payload = item.model_dump(mode="python")
    payload["canary_match_count"] = 2
    with pytest.raises(ValidationError, match="summary") as caught:
        AuditEvent.model_validate(payload)
    assert RAW not in str(caught.value)


def test_detection_none_and_canary_false_are_rejected() -> None:
    with pytest.raises(ValidationError):
        DetectionEvidence.model_validate({"type": "document_canary", "evidence_id": RAW,
            "violation": True, "action": "none"})
    with pytest.raises(ValidationError) as caught:
        DetectionEvidence(type=DetectionType.SYSTEM_CANARY, evidence_id=RAW,
            violation=False, action=DetectionAction.OBSERVED)
    assert RAW not in str(caught.value)


def test_datetime_accepts_offsets_and_normalizes() -> None:
    offset = timezone(timedelta(hours=8))
    audit = event_at(datetime(2026, 8, 11, 12, 0, tzinfo=offset))
    filters = AuditEventFilter(start_time=datetime(2026, 8, 11, 12, 0, tzinfo=offset))
    assert audit.occurred_at == datetime(2026, 8, 11, 4, 0, tzinfo=UTC)
    assert filters.start_time == audit.occurred_at
    with pytest.raises(ValidationError):
        event_at(datetime(2026, 8, 11, 12, 0))


def test_prepare_idempotent_and_full_roundtrip(repository) -> None:
    repository.prepare_schema()
    original = event_at(datetime(2026, 8, 11, 0, 0, tzinfo=UTC))
    repository.append_event(original)
    page = repository.list_events(AuditEventFilter())
    assert page.items == (original,)
    assert page.next_cursor is None
    assert repository.healthcheck() is True


def test_duplicate_rolls_back_and_error_is_minimized(repository) -> None:
    original = event_at(datetime.now(UTC))
    repository.append_event(original)
    with pytest.raises(StorageError) as caught:
        repository.append_event(original)
    rendered = repr(caught.value) + str(caught.value) + repr(caught.value.as_dict())
    assert RAW not in rendered and "sqlite" not in rendered.lower() and "insert" not in rendered.lower()
    assert len(repository.list_events(AuditEventFilter()).items) == 1


def test_child_insert_failure_rolls_back_main_row(repository) -> None:
    original = event_at(datetime.now(UTC))
    def fail_child(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "audit_retrieved_documents" in statement:
            raise RuntimeError(RAW)
    sqlalchemy_event.listen(repository._engine, "before_cursor_execute", fail_child)
    try:
        with pytest.raises(StorageError) as caught:
            repository.append_event(original)
    finally:
        sqlalchemy_event.remove(repository._engine, "before_cursor_execute", fail_child)
    assert RAW not in repr(caught.value) + str(caught.value)
    assert repository.list_events(AuditEventFilter()).items == ()


def test_all_filters_and_closed_time_interval(repository) -> None:
    first = event_at(datetime(2026, 1, 1, tzinfo=UTC), subject="guest-01")
    second = event_at(datetime(2026, 1, 2, tzinfo=UTC), subject="guest-02")
    repository.append_event(first); repository.append_event(second)
    filters = AuditEventFilter(trace_id=first.trace_id, run_id=first.run_id, subject_id=first.subject_id,
        mode=first.mode, event_type=first.event_type, start_time=first.occurred_at, end_time=first.occurred_at)
    assert repository.list_events(filters).items == (first,)


def test_stable_cursor_tie_order_and_offset_equivalence(repository) -> None:
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    ids = sorted((str(uuid4()), str(uuid4()), str(uuid4())))
    for identifier in reversed(ids):
        repository.append_event(event_at(moment, event_id=identifier))
    page1 = repository.list_events(AuditEventFilter(limit=1))
    page2 = repository.list_events(AuditEventFilter(limit=1, cursor=page1.next_cursor))
    page3 = repository.list_events(AuditEventFilter(limit=1, cursor=page2.next_cursor,
        start_time=datetime(2026, 1, 1, 8, tzinfo=timezone(timedelta(hours=8)))))
    assert [page1.items[0].event_id, page2.items[0].event_id, page3.items[0].event_id] == ids
    assert page3.next_cursor is None


@pytest.mark.parametrize("cursor", ["x", "=" * 3, "A" * 513])
def test_cursor_rejects_invalid_values(repository, cursor: str) -> None:
    with pytest.raises((AuditQueryError, ValidationError)) as caught:
        repository.list_events(AuditEventFilter(cursor=cursor))
    assert RAW not in str(caught.value)


def test_cursor_rejects_tamper_and_padding(repository) -> None:
    for number in range(2):
        repository.append_event(event_at(datetime(2026, 1, number + 1, tzinfo=UTC)))
    cursor = repository.list_events(AuditEventFilter(limit=1)).next_cursor
    assert cursor
    tampered = cursor[:-1] + ("A" if cursor[-1] != "A" else "B")
    for invalid in (tampered, cursor + "="):
        with pytest.raises(AuditQueryError):
            repository.list_events(AuditEventFilter(limit=1, cursor=invalid))


def test_cursor_rejects_rechecksummed_noncanonical_timestamp(repository) -> None:
    for number in range(2):
        repository.append_event(event_at(datetime(2026, 1, number + 1, tzinfo=UTC)))
    cursor = repository.list_events(AuditEventFilter(limit=1)).next_cursor
    padding = "=" * ((4 - len(cursor) % 4) % 4)
    payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
    payload["occurred_at"] = "2026-01-01T08:00:00+08:00"
    core = {key: payload[key] for key in ("event_id", "occurred_at", "version")}
    payload["checksum"] = hashlib.sha256(json.dumps(core, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    forged = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    with pytest.raises(AuditQueryError):
        repository.list_events(AuditEventFilter(limit=1, cursor=forged))


@pytest.mark.parametrize("limit", [1, 200])
def test_limit_boundaries(repository, limit: int) -> None:
    assert repository.list_events(AuditEventFilter(limit=limit)).items == ()
@pytest.mark.parametrize("limit", [0, 201, True])
def test_limit_rejects_outside_or_bool(limit) -> None:
    with pytest.raises(ValidationError): AuditEventFilter(limit=limit)


def test_database_drift_detection_action_none_is_rejected(repository) -> None:
    original = event_at(datetime.now(UTC))
    repository.append_event(original)
    with repository._engine.begin() as connection:
        connection.execute(audit_detections.update().values(action="none"))
    with pytest.raises(StorageError):
        repository.list_events(AuditEventFilter())


def test_concurrent_appends_are_complete(repository) -> None:
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    values = [event_at(moment, event_id=str(uuid4())) for _ in range(12)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(repository.append_event, values))
    assert len(repository.list_events(AuditEventFilter(limit=200)).items) == 12


def test_close_blocks_operations(repository) -> None:
    repository.close()
    with pytest.raises(StorageError): repository.healthcheck()


def test_health_requires_prepared_exact_schema(tmp_path: Path) -> None:
    repo = create_audit_repository(RuntimeSettings(), tmp_path)
    with pytest.raises(StorageError): repo.healthcheck()
    repo.close()


def test_prepare_rejects_extra_table_and_column(tmp_path: Path) -> None:
    settings = RuntimeSettings()
    repo = create_audit_repository(settings, tmp_path)
    repo._sqlite_location.prepare_parent()
    malicious = create_engine(repo._engine.url)
    with malicious.begin() as connection:
        connection.execute(text("CREATE TABLE unexpected_table (raw_question TEXT)"))
    malicious.dispose()
    with pytest.raises(StorageError): repo.prepare_schema()
    repo.close()

    other_root = tmp_path / "column-drift"; other_root.mkdir()
    repo = create_audit_repository(settings, other_root)
    repo._sqlite_location.prepare_parent()
    malicious = create_engine(repo._engine.url)
    with malicious.begin() as connection:
        connection.execute(text("CREATE TABLE audit_events (event_id VARCHAR(36) PRIMARY KEY, raw_question TEXT)"))
    malicious.dispose()
    with pytest.raises(StorageError): repo.prepare_schema()
    repo.close()


def test_read_rejects_count_drift(repository) -> None:
    repository.append_event(event_at(datetime.now(UTC)))
    with repository._engine.begin() as connection:
        connection.execute(audit_events.update().values(retrieved_document_count=4))
    with pytest.raises(StorageError):
        repository.list_events(AuditEventFilter())


def test_child_order_roundtrip(repository) -> None:
    base = event_at(datetime.now(UTC)).model_dump(mode="python")
    base["retrieved_documents"] = (
        RetrievedDocumentEvidence(document_id="doc-a", rank=1, similarity_score=.8,
            authorized=True, included_in_context=True, denial_reason=None),
        RetrievedDocumentEvidence(document_id="doc-b", rank=2, similarity_score=.7,
            authorized=False, included_in_context=True, denial_reason="role_not_allowed"),
    )
    base["authorization_denials"] = (
        AuthorizationDenial(document_id="doc-b", reason="role_not_allowed"),
        AuthorizationDenial(document_id="doc-c", reason="role_not_allowed"),
    )
    base["detections"] = (
        DetectionEvidence(type=DetectionType.DOCUMENT_CANARY, evidence_id="a", violation=True, action=DetectionAction.OBSERVED),
        DetectionEvidence(type=DetectionType.UNAUTHORIZED_PROTECTED_FRAGMENT, evidence_id="b", violation=True, action=DetectionAction.OBSERVED),
    )
    for name in ("retrieved_document_count", "unauthorized_context_count", "canary_match_count", "protected_fragment_match_count", "detector_action"):
        base.pop(name)
    original = AuditEvent.model_validate(base)
    repository.append_event(original)
    loaded = repository.list_events(AuditEventFilter()).items[0]
    assert loaded.retrieved_documents == original.retrieved_documents
    assert loaded.authorization_denials == original.authorization_denials
    assert loaded.detections == original.detections


def test_fixed_exceptions_cannot_accept_or_echo_overrides() -> None:
    for error_type in (StorageError, AuditQueryError):
        with pytest.raises(TypeError): error_type(RAW)
        error = error_type()
        for name in ("code", "message", "args"):
            with pytest.raises(AttributeError): setattr(error, name, RAW)
        assert RAW not in repr(error) + str(error) + repr(error.as_dict())


def test_concrete_repository_direct_construction_is_rejected() -> None:
    from dataguard.storage.repository import SQLAlchemyAuditRepository
    with pytest.raises(StorageError):
        SQLAlchemyAuditRepository(StorageBackend.SQLITE, object(), object())


def test_runtime_operation_does_not_recreate_missing_parent(tmp_path: Path) -> None:
    repo = create_audit_repository(RuntimeSettings(), tmp_path)
    repo.prepare_schema()
    repo._engine.dispose()
    artifact_parent = tmp_path / "artifacts"
    moved = tmp_path / "artifacts-moved"
    artifact_parent.rename(moved)
    try:
        operations = (
            lambda: repo.append_event(event_at(datetime.now(UTC))),
            lambda: repo.list_events(AuditEventFilter()),
            repo.healthcheck,
        )
        for operation in operations:
            with pytest.raises(StorageError): operation()
            assert not artifact_parent.exists()
    finally:
        moved.rename(artifact_parent)
        repo.close()


def test_entry_model_dump_and_factory_exceptions_are_minimized(tmp_path: Path, monkeypatch) -> None:
    repo = create_audit_repository(RuntimeSettings(), tmp_path)
    repo.prepare_schema()
    original_event_dump = AuditEvent.model_dump
    monkeypatch.setattr(AuditEvent, "model_dump", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError(RAW)))
    with pytest.raises(StorageError) as caught:
        repo.append_event(event_at(datetime.now(UTC)))
    assert RAW not in repr(caught.value) + str(caught.value)
    monkeypatch.setattr(AuditEvent, "model_dump", original_event_dump)
    original_filter_dump = AuditEventFilter.model_dump
    monkeypatch.setattr(AuditEventFilter, "model_dump", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError(RAW)))
    with pytest.raises(AuditQueryError) as caught:
        repo.list_events(AuditEventFilter())
    assert RAW not in repr(caught.value) + str(caught.value)
    monkeypatch.setattr(AuditEventFilter, "model_dump", original_filter_dump)
    repo.close()
    import dataguard.storage.repository as repository_module
    monkeypatch.setattr(repository_module, "create_engine", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError(RAW)))
    with pytest.raises(StorageError) as caught:
        create_audit_repository(RuntimeSettings(), tmp_path)
    assert RAW not in repr(caught.value) + str(caught.value)


def test_schema_columns_are_exact_and_ddl_compiles() -> None:
    expected = {
        "audit_events": {"event_id","event_type","occurred_at","trace_id","run_id","subject_id","resolved_role","mode","outcome","corpus_version","retrieved_document_count","unauthorized_context_count","canary_match_count","protected_fragment_match_count","detector_action","error_code"},
        "audit_retrieved_documents": {"event_id","position","document_id","rank","similarity_score","authorized","included_in_context","denial_reason"},
        "audit_authorization_denials": {"event_id","position","document_id","reason"},
        "audit_detections": {"event_id","position","type","evidence_id","violation","action"},
    }
    assert {table.name: set(table.c.keys()) for table in metadata.tables.values()} == expected
    for table in metadata.tables.values():
        for dialect in (sqlite.dialect(), postgresql.dialect()):
            assert str(CreateTable(table).compile(dialect=dialect))
    forbidden_exact = {"question","document","context","prompt","reply","model_output","marker","value","sql","path"}
    assert not forbidden_exact.intersection({column.name for table in metadata.tables.values() for column in table.columns})


def test_constructor_has_no_io_and_postgresql_is_lazy(tmp_path: Path, monkeypatch) -> None:
    def forbidden(*args, **kwargs): raise AssertionError("I/O")
    monkeypatch.setattr(Path, "mkdir", forbidden)
    sqlite_repo = create_audit_repository(RuntimeSettings(), tmp_path)
    assert "dataguard.sqlite3" not in repr(sqlite_repo)
    assert not sqlite_repo._sqlite_location.target.exists()
    import psycopg
    monkeypatch.setattr(psycopg, "connect", forbidden)
    postgres = RuntimeSettings(profile="evidence", storage_backend="postgresql",
        database_dsn="postgresql+psycopg://localhost/db")
    pg_repo = create_audit_repository(postgres, tmp_path)
    assert pg_repo._engine.hide_parameters is True
    assert "postgresql+psycopg" not in repr(pg_repo)
    sqlite_repo.close(); pg_repo.close()


def test_hydrate_unexpected_exception_is_minimized(repository, monkeypatch) -> None:
    repository.append_event(event_at(datetime.now(UTC)))
    def corrupt(*_args, **_kwargs): raise RuntimeError(RAW)
    monkeypatch.setattr(type(repository), "_hydrate", corrupt)
    with pytest.raises(StorageError) as caught:
        repository.list_events(AuditEventFilter())
    assert RAW not in repr(caught.value) + str(caught.value) + repr(caught.value.as_dict())


def test_path_escape_file_symlink_and_reparse_are_rejected(tmp_path: Path, monkeypatch) -> None:
    with pytest.raises(StorageError): create_audit_repository(RuntimeSettings(), Path("relative"))
    root_file = tmp_path / "file-root"; root_file.write_text("x")
    repo = create_audit_repository(RuntimeSettings(), root_file)
    with pytest.raises(StorageError): repo.prepare_schema()
    repo.close()
    link_root = tmp_path / "link-root"
    try:
        link_root.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pass
    else:
        repo = create_audit_repository(RuntimeSettings(), link_root)
        with pytest.raises(StorageError): repo.prepare_schema()
        repo.close()
    import dataguard.storage.paths as paths
    original = paths._is_reparse
    monkeypatch.setattr(paths, "_is_reparse", lambda info: True)
    repo = create_audit_repository(RuntimeSettings(), tmp_path)
    with pytest.raises(StorageError): repo.prepare_schema()
    repo.close()


def test_import_has_no_io(monkeypatch) -> None:
    import importlib, dataguard.storage as module
    monkeypatch.setattr(Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(AssertionError("I/O")))
    importlib.reload(module)


def test_fresh_import_does_not_connect_or_create() -> None:
    script = r'''import pathlib, socket, sqlite3, psycopg
def blocked(*args, **kwargs): raise AssertionError("side effect")
pathlib.Path.mkdir = blocked
pathlib.Path.write_bytes = blocked
pathlib.Path.write_text = blocked
socket.create_connection = blocked
sqlite3.connect = blocked
psycopg.connect = blocked
import dataguard.storage
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=Path.cwd(),
        capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
