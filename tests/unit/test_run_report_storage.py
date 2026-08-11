from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event as sqlalchemy_event

from dataguard.config import RuntimeSettings
from dataguard.storage import (
    ErrorCode, EvaluationProfile, EvaluationRun, ReportNotReadyError,
    ReportUnavailableError, ReportValidationError, RunNotFoundError,
    RunStateError, RunStatus, StorageError, create_audit_repository,
)
from dataguard.storage.schema import evaluation_reports, evaluation_runs
from dataguard.validation import validate_evaluation_run_semantics
from tests.support.report_factory import build_valid_report

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UTC = timezone.utc
NOW = datetime(2026, 8, 11, 1, 0, tzinfo=UTC)
RAW = "RAW-RUN-REPORT-SENTINEL"


@pytest.fixture
def run_repository(tmp_path: Path):
    contract_dir = tmp_path / "docs" / "contracts"
    contract_dir.mkdir(parents=True)
    shutil.copyfile(PROJECT_ROOT / "docs" / "contracts" / "report.schema.json",
                    contract_dir / "report.schema.json")
    repo = create_audit_repository(RuntimeSettings(), tmp_path)
    repo.prepare_schema()
    yield repo
    repo.close()


def make_report(run_id: str) -> dict:
    report = build_valid_report()
    report["run_id"] = run_id
    report["profile"] = "exploratory"
    report["portfolio_eligible"] = False
    report["experiment"]["storage_backend"] = "sqlite"
    report["generated_at"] = "2026-08-11T01:00:01Z"
    return report


def running_at(repo, progress: int):
    run = repo.create_run("synthetic-v1", EvaluationProfile.EXPLORATORY, NOW)
    run = repo.start_run(run.run_id, NOW)
    for _ in range(progress):
        run = repo.advance_run(run.run_id, NOW)
    return run


def test_evaluation_run_model_states_and_time_normalization() -> None:
    offset = timezone(timedelta(hours=8))
    queued = EvaluationRun(run_id=str(uuid4()), status="queued",
        scenario_set_version="synthetic-v1", profile="exploratory",
        completed_scenarios=0, total_scenarios=62,
        created_at=datetime(2026, 8, 11, 9, tzinfo=offset),
        updated_at=datetime(2026, 8, 11, 9, tzinfo=offset))
    assert queued.created_at == NOW
    assert validate_evaluation_run_semantics(queued.model_dump(mode="json")) == ()
    invalid = queued.model_dump(mode="python")
    invalid["completed_scenarios"] = 1
    with pytest.raises(ValidationError): EvaluationRun.model_validate(invalid)
    invalid = queued.model_dump(mode="python")
    invalid["created_at"] = NOW + timedelta(seconds=1)
    with pytest.raises(ValidationError): EvaluationRun.model_validate(invalid)
    completed = {**queued.model_dump(mode="python"), "status": "completed",
        "completed_scenarios": 62, "updated_at": NOW + timedelta(seconds=1),
        "completed_at": NOW + timedelta(seconds=1)}
    assert EvaluationRun.model_validate(completed).status is RunStatus.COMPLETED
    assert validate_evaluation_run_semantics(EvaluationRun.model_validate(completed).model_dump(mode="json")) == ()
    completed["completed_at"] = NOW
    with pytest.raises(ValidationError): EvaluationRun.model_validate(completed)
    forged = {**queued.model_dump(mode="python"), "status": "interrupted",
              "failure_code": "model_timeout"}
    with pytest.raises(ValidationError): EvaluationRun.model_validate(forged)
    forged["failure_code"] = "internal_error"
    assert EvaluationRun.model_validate(forged).status is RunStatus.INTERRUPTED


def test_create_is_always_new_queued_and_evidence_requires_postgresql(run_repository) -> None:
    first = run_repository.create_run("synthetic-v1", EvaluationProfile.EXPLORATORY, NOW)
    second = run_repository.create_run("synthetic-v1", EvaluationProfile.EXPLORATORY, NOW)
    assert first.run_id != second.run_id
    assert first.status is RunStatus.QUEUED and first.completed_scenarios == 0
    with pytest.raises(RunStateError):
        run_repository.create_run("synthetic-v1", EvaluationProfile.EVIDENCE, NOW)
    with pytest.raises(RunStateError):
        run_repository.create_run("other-v1", EvaluationProfile.EXPLORATORY, NOW)


def test_list_queued_runs_is_fifo_and_excludes_nonqueued(run_repository) -> None:
    later = run_repository.create_run(
        "synthetic-v1", EvaluationProfile.EXPLORATORY, NOW + timedelta(seconds=1))
    same_time_a = run_repository.create_run(
        "synthetic-v1", EvaluationProfile.EXPLORATORY, NOW)
    same_time_b = run_repository.create_run(
        "synthetic-v1", EvaluationProfile.EXPLORATORY, NOW)
    run_repository.start_run(later.run_id, NOW + timedelta(seconds=1))
    expected = tuple(sorted((same_time_a.run_id, same_time_b.run_id)))
    assert tuple(run.run_id for run in run_repository.list_queued_runs()) == expected


def test_transition_matrix_progress_and_terminal_immutability(run_repository) -> None:
    queued = run_repository.create_run("synthetic-v1", EvaluationProfile.EXPLORATORY, NOW)
    with pytest.raises(RunStateError): run_repository.advance_run(queued.run_id, NOW)
    with pytest.raises(RunStateError): run_repository.fail_run(queued.run_id, ErrorCode.INTERNAL_ERROR, NOW)
    running = run_repository.start_run(queued.run_id, NOW)
    assert running.status is RunStatus.RUNNING
    with pytest.raises(RunStateError): run_repository.start_run(queued.run_id, NOW)
    progressed = run_repository.advance_run(queued.run_id, NOW)
    assert progressed.completed_scenarios == 1
    with pytest.raises(RunStateError):
        run_repository.advance_run(queued.run_id, NOW - timedelta(seconds=1))
    failed = run_repository.fail_run(queued.run_id, ErrorCode.MODEL_TIMEOUT, NOW)
    assert failed.status is RunStatus.FAILED and failed.failure_code is ErrorCode.MODEL_TIMEOUT
    for operation in (run_repository.start_run, run_repository.advance_run):
        with pytest.raises(RunStateError): operation(queued.run_id, NOW)
    with pytest.raises(RunStateError):
        run_repository.fail_run(queued.run_id, ErrorCode.INTERNAL_ERROR, NOW)


def test_concurrent_progress_is_serial_and_stops_before_62(run_repository) -> None:
    run = running_at(run_repository, 0)
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: run_repository.advance_run(run.run_id, NOW), range(10)))
    assert sorted(item.completed_scenarios for item in results) == list(range(1, 11))
    for _ in range(51): run_repository.advance_run(run.run_id, NOW)
    assert run_repository.get_run(run.run_id).completed_scenarios == 61
    with pytest.raises(RunStateError): run_repository.advance_run(run.run_id, NOW)


def test_recovery_updates_only_running_with_fixed_code(run_repository) -> None:
    queued = run_repository.create_run("synthetic-v1", EvaluationProfile.EXPLORATORY, NOW)
    running = running_at(run_repository, 2)
    failed = running_at(run_repository, 1)
    run_repository.fail_run(failed.run_id, ErrorCode.MODEL_TIMEOUT, NOW)
    assert run_repository.recover_interrupted_runs(NOW + timedelta(seconds=1)) == 1
    interrupted = run_repository.get_run(running.run_id)
    assert interrupted.status is RunStatus.INTERRUPTED
    assert interrupted.failure_code is ErrorCode.INTERNAL_ERROR
    assert interrupted.completed_at is None
    assert run_repository.get_run(queued.run_id).status is RunStatus.QUEUED
    assert run_repository.get_run(failed.run_id).status is RunStatus.FAILED
    assert run_repository.recover_interrupted_runs(NOW + timedelta(seconds=2)) == 0


def test_recovery_fault_rolls_back_all(run_repository) -> None:
    runs = (running_at(run_repository, 1), running_at(run_repository, 2))
    def fail(_conn, _cursor, statement, _params, _context, _many):
        if statement.startswith("UPDATE evaluation_runs"):
            raise RuntimeError(RAW)
    sqlalchemy_event.listen(run_repository._engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(StorageError) as caught:
            run_repository.recover_interrupted_runs(NOW + timedelta(seconds=1))
    finally:
        sqlalchemy_event.remove(run_repository._engine, "before_cursor_execute", fail)
    assert RAW not in repr(caught.value) + str(caught.value)
    assert all(run_repository.get_run(run.run_id).status is RunStatus.RUNNING for run in runs)


def test_recovery_rejects_any_running_report_drift_atomically(run_repository) -> None:
    drifted, other = running_at(run_repository, 1), running_at(run_repository, 2)
    with run_repository._engine.begin() as connection:
        connection.execute(evaluation_reports.insert().values(
            run_id=drifted.run_id, report_id=str(uuid4()),
            generated_at="2026-08-11T01:00:00.000000Z",
            canonical_json=RAW, sha256="a" * 64))
    with pytest.raises(StorageError) as caught:
        run_repository.recover_interrupted_runs(NOW + timedelta(seconds=1))
    assert RAW not in repr(caught.value) + str(caught.value) + repr(caught.value.as_dict())
    with run_repository._engine.begin() as connection:
        connection.execute(evaluation_reports.delete().where(
            evaluation_reports.c.run_id == drifted.run_id))
    assert run_repository.get_run(drifted.run_id).status is RunStatus.RUNNING
    assert run_repository.get_run(other.run_id).status is RunStatus.RUNNING


def test_report_four_states_and_missing(run_repository) -> None:
    queued = run_repository.create_run("synthetic-v1", EvaluationProfile.EXPLORATORY, NOW)
    with pytest.raises(ReportNotReadyError): run_repository.get_report(queued.run_id)
    running = run_repository.start_run(queued.run_id, NOW)
    with pytest.raises(ReportNotReadyError): run_repository.get_report(running.run_id)
    run_repository.fail_run(running.run_id, ErrorCode.INTERNAL_ERROR, NOW)
    with pytest.raises(ReportUnavailableError): run_repository.get_report(running.run_id)
    interrupted = running_at(run_repository, 0)
    run_repository.recover_interrupted_runs(NOW + timedelta(seconds=1))
    with pytest.raises(ReportUnavailableError): run_repository.get_report(interrupted.run_id)
    with pytest.raises(RunNotFoundError): run_repository.get_report(str(uuid4()))


def test_complete_persists_one_canonical_report_atomically(run_repository) -> None:
    run = running_at(run_repository, 61)
    report = make_report(run.run_id)
    completed = run_repository.complete_run(run.run_id, report, NOW + timedelta(seconds=1))
    assert completed.status is RunStatus.COMPLETED
    assert completed.completed_scenarios == 62
    assert completed.completed_at == completed.updated_at
    stored = run_repository.get_report(run.run_id)
    expected = json.dumps(report, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode() + b"\n"
    assert stored.canonical_json == expected
    assert stored.as_mapping() == report
    detached = stored.as_mapping(); detached["run_id"] = RAW
    assert stored.as_mapping()["run_id"] == run.run_id
    assert RAW not in repr(stored)
    with pytest.raises(RunStateError):
        run_repository.complete_run(run.run_id, report, NOW + timedelta(seconds=2))


@pytest.mark.parametrize("generated_at", [
    "2026-08-10T23:59:59Z",
    "2026-08-11T01:00:02Z",
])
def test_complete_rejects_report_time_outside_completion_instant(run_repository, generated_at: str) -> None:
    run = running_at(run_repository, 61)
    report = make_report(run.run_id); report["generated_at"] = generated_at
    with pytest.raises(ReportValidationError):
        run_repository.complete_run(run.run_id, report, NOW + timedelta(seconds=1))
    assert run_repository.get_run(run.run_id).status is RunStatus.RUNNING
    with run_repository._engine.connect() as connection:
        assert connection.execute(evaluation_reports.select()).all() == []


def test_complete_accepts_equivalent_offset_completion_time(run_repository) -> None:
    run = running_at(run_repository, 61)
    report = make_report(run.run_id)
    report["generated_at"] = "2026-08-11T09:00:01+08:00"
    completed = run_repository.complete_run(run.run_id, report, NOW + timedelta(seconds=1))
    assert completed.status is RunStatus.COMPLETED
    assert run_repository.get_report(run.run_id).as_mapping()["generated_at"] == report["generated_at"]


def test_prepared_validator_is_cached_for_complete_and_get(run_repository) -> None:
    assert "Validator" not in repr(run_repository)
    contract = run_repository._project_root / "docs" / "contracts" / "report.schema.json"
    contract.unlink()
    run = running_at(run_repository, 61)
    report = make_report(run.run_id)
    run_repository.complete_run(run.run_id, report, NOW + timedelta(seconds=1))
    assert run_repository.get_report(run.run_id).as_mapping() == report


def test_invalid_report_contract_fails_before_database_creation(tmp_path: Path) -> None:
    contract_dir = tmp_path / "docs" / "contracts"; contract_dir.mkdir(parents=True)
    (contract_dir / "report.schema.json").write_text(RAW, encoding="utf-8", newline="\n")
    repo = create_audit_repository(RuntimeSettings(), tmp_path)
    with pytest.raises(StorageError) as caught:
        repo.prepare_schema()
    assert RAW not in repr(caught.value) + str(caught.value)
    assert repo._report_validator is None
    assert not (tmp_path / "artifacts").exists()
    repo.close()


@pytest.mark.parametrize("mutation", ["schema", "semantic", "binding", "backend", "nan"])
def test_invalid_report_writes_nothing(run_repository, mutation: str) -> None:
    run = running_at(run_repository, 61)
    report = make_report(run.run_id)
    if mutation == "schema": report["unknown"] = RAW
    elif mutation == "semantic": report["summary"]["baseline_attacks"]["asr"] = 0.123
    elif mutation == "binding": report["run_id"] = str(uuid4())
    elif mutation == "backend": report["experiment"]["storage_backend"] = "postgresql"
    else: report["summary"]["baseline_attacks"]["asr"] = float("nan")
    with pytest.raises(ReportValidationError) as caught:
        run_repository.complete_run(run.run_id, report, NOW + timedelta(seconds=1))
    assert RAW not in repr(caught.value) + str(caught.value)
    assert run_repository.get_run(run.run_id).status is RunStatus.RUNNING
    with run_repository._engine.connect() as connection:
        assert connection.execute(evaluation_reports.select()).all() == []


@pytest.mark.parametrize("fault_statement", ["INSERT INTO evaluation_reports", "UPDATE evaluation_runs SET"])
def test_complete_fault_rolls_back_run_and_report(run_repository, fault_statement: str) -> None:
    run = running_at(run_repository, 61)
    report = make_report(run.run_id)
    def fail(_conn, _cursor, statement, _params, _context, _many):
        if statement.startswith(fault_statement):
            raise RuntimeError(RAW)
    sqlalchemy_event.listen(run_repository._engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(StorageError) as caught:
            run_repository.complete_run(run.run_id, report, NOW + timedelta(seconds=1))
    finally:
        sqlalchemy_event.remove(run_repository._engine, "before_cursor_execute", fail)
    assert RAW not in repr(caught.value) + str(caught.value)
    assert run_repository.get_run(run.run_id).status is RunStatus.RUNNING
    with run_repository._engine.connect() as connection:
        assert connection.execute(evaluation_reports.select()).all() == []


def test_run_and_report_database_drift_is_minimized(run_repository) -> None:
    queued = run_repository.create_run("synthetic-v1", EvaluationProfile.EXPLORATORY, NOW)
    with run_repository._engine.begin() as connection:
        connection.execute(evaluation_runs.update().where(evaluation_runs.c.run_id == queued.run_id).values(status="completed"))
    with pytest.raises(StorageError): run_repository.get_run(queued.run_id)

    run = running_at(run_repository, 61)
    run_repository.complete_run(run.run_id, make_report(run.run_id), NOW + timedelta(seconds=1))
    with run_repository._engine.begin() as connection:
        connection.execute(evaluation_reports.update().where(evaluation_reports.c.run_id == run.run_id).values(canonical_json=RAW))
    with pytest.raises(StorageError) as caught:
        run_repository.get_report(run.run_id)
    assert RAW not in repr(caught.value) + str(caught.value)
