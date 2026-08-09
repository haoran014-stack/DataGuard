"""Tests for error catalog, Problem Details, chat, and run-state semantics."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import pytest
import yaml

from dataguard.validation import (
    FIXED_BLOCKED_REPLY,
    ErrorCatalog,
    load_error_catalog,
    validate_chat_response_semantics,
    validate_evaluation_run_semantics,
    validate_problem_details_semantics,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ERROR_CATALOG_PATH = PROJECT_ROOT / "docs" / "contracts" / "error-codes.yaml"
TRACE_ID = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def writable_tmp_path() -> Path:
    base = PROJECT_ROOT / ".pytest_cache" / "dataguard-error-tests"
    base.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=base) as directory:
        yield Path(directory)


def error_catalog() -> ErrorCatalog:
    result = load_error_catalog(ERROR_CATALOG_PATH)
    assert result.catalog is not None, [issue.as_dict() for issue in result.issues]
    return result.catalog


def valid_problem(code: str = "invalid_request") -> dict[str, Any]:
    catalog = error_catalog()
    definition = catalog.errors[code]
    return {
        "type": f"{catalog.type_base}{code}",
        "title": definition.title,
        "status": definition.status,
        "detail": definition.detail,
        "code": code,
        "trace_id": TRACE_ID,
        "retryable": definition.retryable,
    }


def valid_run(status: str) -> dict[str, Any]:
    run = {
        "run_id": TRACE_ID,
        "status": status,
        "scenario_set_version": "synthetic-v1",
        "profile": "exploratory",
        "completed_scenarios": 0,
        "total_scenarios": 62,
        "created_at": "2026-08-09T00:00:00Z",
        "updated_at": "2026-08-09T00:01:00Z",
        "completed_at": None,
        "failure_code": None,
    }
    if status == "running":
        run["completed_scenarios"] = 17
    elif status == "completed":
        run["completed_scenarios"] = 62
        run["completed_at"] = "2026-08-09T00:02:00Z"
    elif status in {"failed", "interrupted"}:
        run["completed_scenarios"] = 17
        run["failure_code"] = "internal_error"
    return run


def write_catalog_variant(
    directory: Path,
    mutate: Any,
) -> Path:
    payload = yaml.safe_load(ERROR_CATALOG_PATH.read_text(encoding="utf-8"))
    mutate(payload)
    path = directory / "error-catalog-variant.yaml"
    path.write_bytes(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False).encode("utf-8")
    )
    return path


def test_repository_error_catalog_loads_as_closed_definitions() -> None:
    result = load_error_catalog(ERROR_CATALOG_PATH)

    assert result.ok
    assert result.catalog is not None
    assert len(result.catalog.errors) == 16
    assert result.catalog.type_base == "https://dataguard.local/problems/"


def test_error_catalog_rejects_duplicate_keys_without_echo(
    writable_tmp_path: Path,
) -> None:
    raw = ERROR_CATALOG_PATH.read_bytes()
    altered = raw.replace(
        b"  - code: invalid_request\n",
        b"  - code: invalid_request\n    code: DO_NOT_ECHO_DUPLICATE\n",
        1,
    )
    path = writable_tmp_path / "duplicate-error.yaml"
    path.write_bytes(altered)

    result = load_error_catalog(path)
    rendered = repr([issue.as_dict() for issue in result.issues])

    assert not result.ok
    assert {issue.code for issue in result.issues} == {"error_catalog_read_error"}
    assert "DO_NOT_ECHO_DUPLICATE" not in rendered


def test_error_catalog_rejects_missing_error_code(writable_tmp_path: Path) -> None:
    path = write_catalog_variant(
        writable_tmp_path,
        lambda payload: payload["errors"].pop(),
    )

    result = load_error_catalog(path)

    assert not result.ok
    assert "error_catalog_invalid" in {issue.code for issue in result.issues}


def test_error_catalog_rejects_additional_error_code_without_echo(
    writable_tmp_path: Path,
) -> None:
    def add_error(payload: dict[str, Any]) -> None:
        extra = deepcopy(payload["errors"][0])
        extra["code"] = "DO_NOT_ECHO_EXTRA_CODE"
        payload["errors"].append(extra)

    path = write_catalog_variant(writable_tmp_path, add_error)
    result = load_error_catalog(path)
    rendered = repr([issue.as_dict() for issue in result.issues])

    assert not result.ok
    assert "error_catalog_invalid" in {issue.code for issue in result.issues}
    assert "DO_NOT_ECHO_EXTRA_CODE" not in rendered


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", 2),
        ("format", "other-problem-format"),
        ("media_type", "application/json"),
        ("type_base", "https://other.invalid/problems/"),
        ("required_fields", ["type", "status", "code"]),
        (
            "rules",
            {
                "client_branch_field": "title",
                "raw_content_forbidden": True,
                "stack_trace_forbidden": True,
                "guarded_detector_block_is_problem": False,
            },
        ),
    ],
)
def test_error_catalog_rejects_fixed_top_level_drift(
    writable_tmp_path: Path,
    field: str,
    value: Any,
) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload[field] = value

    result = load_error_catalog(write_catalog_variant(writable_tmp_path, mutate))

    assert not result.ok
    assert "error_catalog_invalid" in {issue.code for issue in result.issues}


def test_error_catalog_rejects_unknown_top_level_field(writable_tmp_path: Path) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["unexpected_field"] = True

    result = load_error_catalog(write_catalog_variant(writable_tmp_path, mutate))

    assert not result.ok
    assert "error_catalog_invalid" in {issue.code for issue in result.issues}


@pytest.mark.parametrize(
    ("field", "value"),
    [("status", 399), ("retryable", "false")],
)
def test_error_catalog_rejects_invalid_error_definition_types(
    writable_tmp_path: Path,
    field: str,
    value: Any,
) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["errors"][0][field] = value

    result = load_error_catalog(write_catalog_variant(writable_tmp_path, mutate))

    assert not result.ok
    assert "error_catalog_invalid" in {issue.code for issue in result.issues}


def test_error_catalog_rejects_fixed_blocked_reply_drift(
    writable_tmp_path: Path,
) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["normal_blocked_response"]["reply"] = "Changed blocked reply"

    result = load_error_catalog(write_catalog_variant(writable_tmp_path, mutate))

    assert not result.ok
    assert "error_catalog_invalid" in {issue.code for issue in result.issues}


def test_error_catalog_requires_nonempty_block_behavior(writable_tmp_path: Path) -> None:
    def mutate(payload: dict[str, Any]) -> None:
        payload["normal_blocked_response"]["behavior"] = ""

    result = load_error_catalog(write_catalog_variant(writable_tmp_path, mutate))

    assert not result.ok
    assert "error_catalog_invalid" in {issue.code for issue in result.issues}


def test_problem_details_matches_every_fixed_catalog_field() -> None:
    assert validate_problem_details_semantics(valid_problem(), error_catalog()) == ()


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("status", 401, "problem_status_mismatch"),
        ("retryable", True, "problem_retryable_mismatch"),
        ("type", "https://dataguard.local/problems/other", "problem_type_mismatch"),
    ],
)
def test_problem_details_cannot_drift_from_catalog(
    field: str,
    value: Any,
    expected_code: str,
) -> None:
    problem = valid_problem()
    problem[field] = value

    issues = validate_problem_details_semantics(problem, error_catalog())

    assert expected_code in {issue.code for issue in issues}


def test_problem_details_allows_nonempty_human_readable_text_changes() -> None:
    problem = valid_problem()
    problem["title"] = "Alternative concise title"
    problem["detail"] = "Alternative bounded explanation for a local caller."

    assert validate_problem_details_semantics(problem, error_catalog()) == ()


def test_problem_details_requires_catalog_retryability_even_if_field_is_omitted() -> None:
    problem = valid_problem()
    del problem["retryable"]

    assert "problem_retryable_mismatch" in {
        issue.code for issue in validate_problem_details_semantics(problem, error_catalog())
    }


def test_problem_details_rejects_unknown_code_without_echo() -> None:
    problem = valid_problem()
    problem["code"] = "DO_NOT_ECHO_UNKNOWN_CODE"

    first = validate_problem_details_semantics(problem, error_catalog())
    second = validate_problem_details_semantics(problem, error_catalog())
    rendered = repr([issue.as_dict() for issue in first])

    assert first == second
    assert [issue.code for issue in first] == ["problem_unknown_code"]
    assert "DO_NOT_ECHO_UNKNOWN_CODE" not in rendered


@pytest.mark.parametrize(
    ("mode", "response"),
    [
        (
            "baseline",
            {"reply": "Synthetic answer", "trace_id": TRACE_ID, "outcome": "answered"},
        ),
        (
            "guarded",
            {"reply": "Synthetic answer", "trace_id": TRACE_ID, "outcome": "answered"},
        ),
        (
            "guarded",
            {"reply": FIXED_BLOCKED_REPLY, "trace_id": TRACE_ID, "outcome": "blocked"},
        ),
    ],
)
def test_valid_chat_response_semantics(mode: str, response: dict[str, Any]) -> None:
    assert validate_chat_response_semantics(mode, response) == ()


@pytest.mark.parametrize(
    ("mode", "reply", "outcome", "expected_code"),
    [
        ("baseline", FIXED_BLOCKED_REPLY, "blocked", "chat_baseline_blocked"),
        ("guarded", "Wrong blocked text", "blocked", "chat_block_reply_mismatch"),
        ("guarded", FIXED_BLOCKED_REPLY, "answered", "chat_answered_uses_block_reply"),
    ],
)
def test_invalid_chat_response_semantics(
    mode: str,
    reply: str,
    outcome: str,
    expected_code: str,
) -> None:
    response = {"reply": reply, "trace_id": TRACE_ID, "outcome": outcome}

    issues = validate_chat_response_semantics(mode, response)

    assert expected_code in {issue.code for issue in issues}


def test_chat_issue_does_not_echo_wrong_reply() -> None:
    raw_reply = "DO_NOT_ECHO_RAW_REPLY"
    issues = validate_chat_response_semantics(
        "guarded",
        {"reply": raw_reply, "trace_id": TRACE_ID, "outcome": "blocked"},
    )

    assert raw_reply not in repr([issue.as_dict() for issue in issues])


@pytest.mark.parametrize(
    "status",
    ["queued", "running", "completed", "failed", "interrupted"],
)
def test_valid_evaluation_run_state_combinations(status: str) -> None:
    assert validate_evaluation_run_semantics(valid_run(status)) == ()


@pytest.mark.parametrize(
    ("status", "field", "value", "expected_code"),
    [
        ("queued", "completed_scenarios", 1, "run_progress_mismatch"),
        ("queued", "completed_at", "2026-08-09T00:02:00Z", "run_completed_at_mismatch"),
        ("queued", "failure_code", "internal_error", "run_failure_code_mismatch"),
        ("running", "completed_scenarios", 62, "run_progress_mismatch"),
        ("running", "completed_at", "2026-08-09T00:02:00Z", "run_completed_at_mismatch"),
        ("running", "failure_code", "internal_error", "run_failure_code_mismatch"),
        ("completed", "completed_scenarios", 61, "run_progress_mismatch"),
        ("completed", "completed_at", None, "run_completed_at_mismatch"),
        ("completed", "failure_code", "internal_error", "run_failure_code_mismatch"),
        ("failed", "completed_at", "2026-08-09T00:02:00Z", "run_completed_at_mismatch"),
        ("failed", "failure_code", None, "run_failure_code_mismatch"),
        ("interrupted", "completed_at", "2026-08-09T00:02:00Z", "run_completed_at_mismatch"),
        ("interrupted", "failure_code", None, "run_failure_code_mismatch"),
    ],
)
def test_invalid_evaluation_run_state_combinations(
    status: str,
    field: str,
    value: Any,
    expected_code: str,
) -> None:
    run = valid_run(status)
    run[field] = value

    issues = validate_evaluation_run_semantics(run)

    assert expected_code in {issue.code for issue in issues}


@pytest.mark.parametrize("status", ["failed", "interrupted"])
def test_failed_and_interrupted_preserve_schema_allowed_progress(status: str) -> None:
    run = valid_run(status)
    run["completed_scenarios"] = 62

    assert validate_evaluation_run_semantics(run) == ()
