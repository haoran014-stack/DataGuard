"""Semantic checks for structurally valid chat and evaluation-run mappings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from dataguard.validation.issues import ValidationIssue, stable_issue_order


FIXED_BLOCKED_REPLY = (
    "The response was blocked by DataGuard policy. / 响应已被 DataGuard 防护策略阻断。"
)


def validate_chat_response_semantics(
    mode: str,
    response: Mapping[str, Any],
) -> tuple[ValidationIssue, ...]:
    """Enforce the locked baseline/guarded response behavior."""

    issues: list[ValidationIssue] = []
    outcome = response.get("outcome")
    reply = response.get("reply")
    if mode == "baseline" and outcome == "blocked":
        issues.append(ValidationIssue.create("chat_baseline_blocked", ("chat", "outcome")))
    if mode == "guarded" and outcome == "blocked" and reply != FIXED_BLOCKED_REPLY:
        issues.append(
            ValidationIssue.create("chat_block_reply_mismatch", ("chat", "reply"))
        )
    if outcome == "answered" and reply == FIXED_BLOCKED_REPLY:
        issues.append(
            ValidationIssue.create("chat_answered_uses_block_reply", ("chat", "reply"))
        )
    return tuple(sorted(issues, key=stable_issue_order))


def validate_evaluation_run_semantics(
    run: Mapping[str, Any],
) -> tuple[ValidationIssue, ...]:
    """Validate progress and terminal fields for the five locked run states."""

    issues: list[ValidationIssue] = []
    status = run.get("status")
    completed = run.get("completed_scenarios")
    completed_at = run.get("completed_at")
    failure_code = run.get("failure_code")

    if status == "queued":
        if completed != 0:
            issues.append(
                ValidationIssue.create("run_progress_mismatch", ("run", "completed_scenarios"))
            )
        if completed_at is not None:
            issues.append(
                ValidationIssue.create("run_completed_at_mismatch", ("run", "completed_at"))
            )
        if failure_code is not None:
            issues.append(
                ValidationIssue.create("run_failure_code_mismatch", ("run", "failure_code"))
            )
    elif status == "running":
        if not isinstance(completed, int) or isinstance(completed, bool) or not 0 <= completed < 62:
            issues.append(
                ValidationIssue.create("run_progress_mismatch", ("run", "completed_scenarios"))
            )
        if completed_at is not None:
            issues.append(
                ValidationIssue.create("run_completed_at_mismatch", ("run", "completed_at"))
            )
        if failure_code is not None:
            issues.append(
                ValidationIssue.create("run_failure_code_mismatch", ("run", "failure_code"))
            )
    elif status == "completed":
        if completed != 62:
            issues.append(
                ValidationIssue.create("run_progress_mismatch", ("run", "completed_scenarios"))
            )
        if completed_at is None:
            issues.append(
                ValidationIssue.create("run_completed_at_mismatch", ("run", "completed_at"))
            )
        if failure_code is not None:
            issues.append(
                ValidationIssue.create("run_failure_code_mismatch", ("run", "failure_code"))
            )
    elif status in {"failed", "interrupted"}:
        if completed_at is not None:
            issues.append(
                ValidationIssue.create("run_completed_at_mismatch", ("run", "completed_at"))
            )
        if failure_code is None:
            issues.append(
                ValidationIssue.create("run_failure_code_mismatch", ("run", "failure_code"))
            )

    return tuple(sorted(issues, key=stable_issue_order))

