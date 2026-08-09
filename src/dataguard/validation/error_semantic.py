"""Closed error-catalog loading and RFC Problem Details semantic checks."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from dataguard.validation.api_semantic import FIXED_BLOCKED_REPLY
from dataguard.validation.issues import ValidationIssue, stable_issue_order
from dataguard.validation.loading import _DuplicateKeyError, _UniqueKeySafeLoader


TYPE_BASE = "https://dataguard.local/problems/"
EXPECTED_ERROR_CODES = frozenset(
    {
        "invalid_request",
        "subject_not_found",
        "corpus_not_found",
        "scenario_set_not_found",
        "run_not_found",
        "report_not_ready",
        "report_unavailable",
        "ollama_unavailable",
        "generation_model_unavailable",
        "embedding_model_unavailable",
        "storage_unavailable",
        "model_timeout",
        "model_protocol_error",
        "experiment_manifest_mismatch",
        "context_budget_exceeded",
        "internal_error",
    }
)
EXPECTED_REQUIRED_FIELDS = frozenset(
    {"type", "title", "status", "detail", "code", "trace_id"}
)
EXPECTED_TOP_LEVEL_FIELDS = frozenset(
    {
        "version",
        "format",
        "media_type",
        "type_base",
        "required_fields",
        "rules",
        "errors",
        "normal_blocked_response",
    }
)
EXPECTED_RULES = {
    "client_branch_field": "code",
    "raw_content_forbidden": True,
    "stack_trace_forbidden": True,
    "guarded_detector_block_is_problem": False,
}


@dataclass(frozen=True, slots=True)
class ErrorDefinition:
    code: str
    status: int
    retryable: bool
    title: str
    detail: str


@dataclass(frozen=True, slots=True)
class ErrorCatalog:
    type_base: str
    errors: Mapping[str, ErrorDefinition]


@dataclass(frozen=True, slots=True)
class ErrorCatalogLoadResult:
    catalog: ErrorCatalog | None
    issues: tuple[ValidationIssue, ...]

    @property
    def ok(self) -> bool:
        return self.catalog is not None and not self.issues


def load_error_catalog(path: Path) -> ErrorCatalogLoadResult:
    """Load the repository-owned closed error catalog without value-bearing errors."""

    try:
        text = path.read_text(encoding="utf-8")
        payload = yaml.load(text, Loader=_UniqueKeySafeLoader)
    except (OSError, UnicodeError, yaml.YAMLError, _DuplicateKeyError):
        return ErrorCatalogLoadResult(
            catalog=None,
            issues=(
                ValidationIssue.create("error_catalog_read_error", ("error_catalog",)),
            ),
        )

    if not isinstance(payload, dict):
        return ErrorCatalogLoadResult(
            catalog=None,
            issues=(ValidationIssue.create("error_catalog_invalid", ("error_catalog",)),),
        )
    issues: list[ValidationIssue] = []
    if set(payload) != EXPECTED_TOP_LEVEL_FIELDS:
        issues.append(ValidationIssue.create("error_catalog_invalid", ("error_catalog",)))
    for field, expected in (
        ("version", 1),
        ("format", "rfc9457-problem-details"),
        ("media_type", "application/problem+json"),
        ("type_base", TYPE_BASE),
    ):
        if payload.get(field) != expected:
            issues.append(
                ValidationIssue.create("error_catalog_invalid", ("error_catalog", field))
            )

    required_fields = payload.get("required_fields")
    if (
        not isinstance(required_fields, list)
        or len(required_fields) != len(EXPECTED_REQUIRED_FIELDS)
        or set(required_fields) != EXPECTED_REQUIRED_FIELDS
    ):
        issues.append(
            ValidationIssue.create(
                "error_catalog_invalid", ("error_catalog", "required_fields")
            )
        )

    rules = payload.get("rules")
    if not isinstance(rules, dict) or rules != EXPECTED_RULES:
        issues.append(
            ValidationIssue.create("error_catalog_invalid", ("error_catalog", "rules"))
        )

    normal_block = payload.get("normal_blocked_response")
    if not isinstance(normal_block, dict) or set(normal_block) != {
        "status",
        "outcome",
        "reply",
        "behavior",
    }:
        issues.append(
            ValidationIssue.create(
                "error_catalog_invalid", ("error_catalog", "normal_blocked_response")
            )
        )
    else:
        normal_checks = (
            ("status", normal_block.get("status") == 200),
            ("outcome", normal_block.get("outcome") == "blocked"),
            ("reply", normal_block.get("reply") == FIXED_BLOCKED_REPLY),
            (
                "behavior",
                isinstance(normal_block.get("behavior"), str)
                and bool(normal_block.get("behavior")),
            ),
        )
        issues.extend(
            ValidationIssue.create(
                "error_catalog_invalid",
                ("error_catalog", "normal_blocked_response", field),
            )
            for field, valid in normal_checks
            if not valid
        )

    definitions = payload.get("errors")
    if not isinstance(definitions, list):
        issues.append(
            ValidationIssue.create("error_catalog_invalid", ("error_catalog", "errors"))
        )
        definitions = []

    parsed: dict[str, ErrorDefinition] = {}
    for index, definition in enumerate(definitions):
        path_prefix = ("error_catalog", "errors", index)
        if not isinstance(definition, dict) or set(definition) != {
            "code",
            "status",
            "retryable",
            "title",
            "detail",
        }:
            issues.append(ValidationIssue.create("error_catalog_invalid", path_prefix))
            continue
        code = definition["code"]
        status = definition["status"]
        retryable = definition["retryable"]
        title = definition["title"]
        detail = definition["detail"]
        valid = (
            isinstance(code, str)
            and bool(code)
            and type(status) is int
            and 400 <= status <= 599
            and type(retryable) is bool
            and isinstance(title, str)
            and bool(title)
            and isinstance(detail, str)
            and bool(detail)
            and code not in parsed
        )
        if not valid:
            issues.append(ValidationIssue.create("error_catalog_invalid", path_prefix))
            continue
        parsed[code] = ErrorDefinition(
            code=code,
            status=status,
            retryable=retryable,
            title=title,
            detail=detail,
        )

    if set(parsed) != EXPECTED_ERROR_CODES:
        issues.append(
            ValidationIssue.create("error_catalog_invalid", ("error_catalog", "errors"))
        )

    ordered = tuple(sorted(set(issues), key=stable_issue_order))
    if ordered:
        return ErrorCatalogLoadResult(catalog=None, issues=ordered)
    return ErrorCatalogLoadResult(
        catalog=ErrorCatalog(type_base=TYPE_BASE, errors=parsed),
        issues=(),
    )


def validate_problem_details_semantics(
    problem: Mapping[str, Any],
    catalog: ErrorCatalog,
) -> tuple[ValidationIssue, ...]:
    """Bind stable machine fields while leaving human-readable text flexible."""

    code = problem.get("code")
    definition = catalog.errors.get(code) if isinstance(code, str) else None
    if definition is None:
        return (ValidationIssue.create("problem_unknown_code", ("problem", "code")),)

    checks = (
        ("status", definition.status, "problem_status_mismatch"),
        ("retryable", definition.retryable, "problem_retryable_mismatch"),
        ("type", f"{catalog.type_base}{definition.code}", "problem_type_mismatch"),
    )
    issues = [
        ValidationIssue.create(issue_code, ("problem", field))
        for field, expected, issue_code in checks
        if problem.get(field) != expected
    ]
    return tuple(sorted(issues, key=stable_issue_order))
