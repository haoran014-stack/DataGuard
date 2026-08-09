"""Semantic tests for the complete DataGuard v1 report mapping."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from dataguard.validation import ABS_TOL, validate_report_semantics
from tests.support.report_factory import build_valid_report, report_schema_errors


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def set_path(mapping: dict[str, Any], path: tuple[str | int, ...], value: Any) -> None:
    cursor: Any = mapping
    for part in path[:-1]:
        cursor = cursor[part]
    cursor[path[-1]] = value


def semantic_codes(report: dict[str, Any]) -> set[str]:
    return {issue.code for issue in validate_report_semantics(report)}


def test_complete_report_is_schema_valid_and_semantically_consistent() -> None:
    report = build_valid_report()

    assert report_schema_errors(report, PROJECT_ROOT) == []
    assert validate_report_semantics(report) == ()


@pytest.mark.parametrize(
    ("path", "value", "expected_code"),
    [
        (
            ("summary", "baseline_attack_delivery_rate", "numerator"),
            31,
            "report_rate_numerator_mismatch",
        ),
        (
            ("summary", "baseline_attack_delivery_rate", "denominator"),
            31,
            "report_rate_denominator_mismatch",
        ),
        (
            ("summary", "baseline_attack_delivery_rate", "value"),
            0.5,
            "report_rate_value_mismatch",
        ),
        (
            ("summary", "baseline_attacks", "successes"),
            7,
            "report_aggregate_mismatch",
        ),
        (
            (
                "summary",
                "baseline_attacks",
                "by_family",
                "direct_prompt_injection",
                "successes",
            ),
            3,
            "report_aggregate_mismatch",
        ),
        (
            (
                "summary",
                "baseline_attacks",
                "by_family",
                "direct_prompt_injection",
                "asr",
            ),
            0.5,
            "report_aggregate_mismatch",
        ),
    ],
)
def test_report_rate_and_attack_aggregate_tampering_is_rejected(
    path: tuple[str | int, ...],
    value: Any,
    expected_code: str,
) -> None:
    report = build_valid_report()
    set_path(report, path, value)

    assert expected_code in semantic_codes(report)


def test_numeric_comparison_uses_locked_absolute_tolerance() -> None:
    accepted = build_valid_report()
    accepted["summary"]["baseline_attacks"]["asr"] += ABS_TOL / 2
    rejected = build_valid_report()
    rejected["summary"]["baseline_attacks"]["asr"] += ABS_TOL * 2

    assert validate_report_semantics(accepted) == ()
    assert "report_aggregate_mismatch" in semantic_codes(rejected)


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("attack_delivery", "report_rate_numerator_mismatch"),
        ("retrieval_violation", "report_rate_numerator_mismatch"),
        ("guarded_unauthorized_document", "report_summary_mismatch"),
        ("guarded_final_leak", "report_summary_mismatch"),
        ("qa_pass", "report_rate_numerator_mismatch"),
        ("qa_block", "report_rate_numerator_mismatch"),
        ("indeterminate", "report_summary_mismatch"),
        ("prevention_distribution", "report_summary_mismatch"),
        ("missing_prevention", "report_prevention_stage_mismatch"),
    ],
)
def test_summary_is_recomputed_from_scenario_results(
    mutation: str,
    expected_code: str,
) -> None:
    report = build_valid_report()
    if mutation == "attack_delivery":
        report["scenario_results"][30]["baseline"]["attack_delivered"] = False
    elif mutation == "retrieval_violation":
        report["scenario_results"][46]["baseline"]["retrieval_evidence"][0][
            "included_in_context"
        ] = False
    elif mutation == "guarded_unauthorized_document":
        report["scenario_results"][46]["guarded"]["retrieval_evidence"] = [
            {
                "document_id": "synthetic-unauthorized-doc",
                "rank": 1,
                "similarity_score": 0.5,
                "authorized": False,
                "included_in_context": True,
                "denial_reason": None,
            }
        ]
    elif mutation == "guarded_final_leak":
        guarded = report["scenario_results"][32]["guarded"]
        guarded["final_leak_count"] = 1
        guarded["judgment"] = "attack_succeeded"
    elif mutation == "qa_pass":
        guarded = report["scenario_results"][0]["guarded"]
        guarded["fact_assertion_passed"] = False
        guarded["judgment"] = "authorized_qa_fail"
    elif mutation == "qa_block":
        guarded = report["scenario_results"][0]["guarded"]
        guarded["outcome"] = "blocked"
        guarded["fact_assertion_passed"] = False
        guarded["judgment"] = "false_rejection"
    elif mutation == "indeterminate":
        baseline = report["scenario_results"][32]["baseline"]
        baseline["outcome"] = "failed"
        baseline["judgment"] = "indeterminate"
        baseline["error_code"] = "internal_error"
    elif mutation == "prevention_distribution":
        report["scenario_results"][30]["prevention_stage"] = "role_filter"
    else:
        report["scenario_results"][30]["prevention_stage"] = None

    assert expected_code in semantic_codes(report)


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("failed_without_error", "report_mode_failed_consistency"),
        ("failed_wrong_judgment", "report_mode_failed_consistency"),
        ("nonfailed_indeterminate", "report_mode_nonfailed_consistency"),
        ("nonfailed_error", "report_mode_nonfailed_consistency"),
        ("attack_success_wrong", "report_attack_judgment_mismatch"),
        ("attack_prevented_wrong", "report_attack_judgment_mismatch"),
        ("qa_answered_wrong", "report_qa_judgment_mismatch"),
        ("qa_blocked_wrong", "report_qa_judgment_mismatch"),
        ("baseline_blocked", "report_baseline_blocked"),
    ],
)
def test_mode_outcome_judgment_error_and_fact_relationships(
    mutation: str,
    expected_code: str,
) -> None:
    report = build_valid_report()
    if mutation == "failed_without_error":
        result = report["scenario_results"][32]["baseline"]
        result["outcome"] = "failed"
        result["judgment"] = "indeterminate"
    elif mutation == "failed_wrong_judgment":
        result = report["scenario_results"][32]["baseline"]
        result["outcome"] = "failed"
        result["error_code"] = "internal_error"
    elif mutation == "nonfailed_indeterminate":
        report["scenario_results"][32]["baseline"]["judgment"] = "indeterminate"
    elif mutation == "nonfailed_error":
        report["scenario_results"][32]["baseline"]["error_code"] = "internal_error"
    elif mutation == "attack_success_wrong":
        report["scenario_results"][30]["baseline"]["judgment"] = "attack_prevented"
    elif mutation == "attack_prevented_wrong":
        report["scenario_results"][32]["baseline"]["judgment"] = "attack_succeeded"
    elif mutation == "qa_answered_wrong":
        report["scenario_results"][0]["guarded"]["judgment"] = "authorized_qa_fail"
    elif mutation == "qa_blocked_wrong":
        guarded = report["scenario_results"][0]["guarded"]
        guarded["outcome"] = "blocked"
        guarded["fact_assertion_passed"] = False
    else:
        report["scenario_results"][32]["baseline"]["outcome"] = "blocked"

    assert expected_code in semantic_codes(report)


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("actual", 0.3, "report_gate_actual_mismatch"),
        ("operator", "<=", "report_gate_definition_mismatch"),
        ("threshold", 0.3, "report_gate_definition_mismatch"),
        ("passed", False, "report_gate_passed_mismatch"),
    ],
)
def test_gate_fields_are_bound_to_recomputed_values_and_locked_definition(
    field: str,
    value: Any,
    expected_code: str,
) -> None:
    report = build_valid_report()
    report["gates"]["baseline_total_asr"][field] = value

    assert expected_code in semantic_codes(report)


def test_overall_gate_equals_every_declared_component_boolean() -> None:
    report = build_valid_report()
    report["gates"]["comparability_passed"] = False

    codes = semantic_codes(report)

    assert "report_overall_gate_mismatch" in codes
    assert "report_portfolio_ineligible" in codes


@pytest.mark.parametrize(
    "mutation",
    [
        "profile",
        "storage",
        "strict",
        "comparability",
        "overall",
        "indeterminate_gate",
        "derived_gate_failure",
    ],
)
def test_portfolio_true_requires_every_locked_evidence_condition(mutation: str) -> None:
    report = build_valid_report()
    if mutation == "profile":
        report["profile"] = "exploratory"
    elif mutation == "storage":
        report["experiment"]["storage_backend"] = "sqlite"
    elif mutation == "strict":
        report["gates"]["strict_manifest_passed"] = False
    elif mutation == "comparability":
        report["gates"]["comparability_passed"] = False
    elif mutation == "overall":
        report["gates"]["overall_passed"] = False
    elif mutation == "indeterminate_gate":
        gate = report["gates"]["no_indeterminate_mode_results"]
        gate["actual"] = 1
        gate["passed"] = False
    else:
        guarded = report["scenario_results"][32]["guarded"]
        guarded["final_leak_count"] = 1
        guarded["judgment"] = "attack_succeeded"

    assert "report_portfolio_ineligible" in semantic_codes(report)


def test_portfolio_false_is_allowed_even_when_all_evidence_conditions_pass() -> None:
    report = build_valid_report()
    report["portfolio_eligible"] = False

    assert validate_report_semantics(report) == ()


def test_report_issues_are_stable_complete_and_do_not_echo_identifiers() -> None:
    report = build_valid_report()
    report["report_id"] = "DO-NOT-ECHO-REPORT-ID"
    report["scenario_results"][0]["scenario_id"] = "DO-NOT-ECHO-SCENARIO-ID"
    report["summary"]["baseline_attack_delivery_rate"]["value"] = 0.5
    report["summary"]["baseline_attacks"]["successes"] = 7
    report["scenario_results"][32]["baseline"]["judgment"] = "attack_succeeded"

    first = validate_report_semantics(report)
    second = validate_report_semantics(report)
    rendered = repr([issue.as_dict() for issue in first])

    assert first == second
    assert {
        "report_rate_value_mismatch",
        "report_aggregate_mismatch",
        "report_attack_judgment_mismatch",
    } <= {issue.code for issue in first}
    assert "DO-NOT-ECHO-REPORT-ID" not in rendered
    assert "DO-NOT-ECHO-SCENARIO-ID" not in rendered
