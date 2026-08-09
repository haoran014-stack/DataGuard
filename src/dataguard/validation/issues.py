"""Stable, minimized validation issues that never contain fixture values."""

from __future__ import annotations

from dataclasses import dataclass


PathPart = str | int

_MESSAGES = {
    "fixture_read_error": "The fixture could not be read.",
    "fixture_invalid_utf8": "The fixture is not valid UTF-8.",
    "fixture_utf8_bom": "The fixture must not contain a UTF-8 byte-order mark.",
    "fixture_non_lf_newline": "The fixture must use LF line endings only.",
    "yaml_duplicate_key": "The YAML document contains a duplicate mapping key.",
    "yaml_parse_error": "The YAML document could not be parsed safely.",
    "yaml_root_type": "The YAML document root must be a mapping.",
    "schema_read_error": "The JSON Schema could not be read.",
    "schema_definition_error": "The JSON Schema definition is invalid.",
    "schema_validation_error": "The fixture does not satisfy its JSON Schema.",
    "model_validation_error": "The fixture does not satisfy its typed domain model.",
    "semantic_duplicate_subject_id": "A synthetic subject identifier is duplicated.",
    "semantic_duplicate_document_id": "A document identifier is duplicated.",
    "semantic_duplicate_scenario_id": "A scenario identifier is duplicated.",
    "semantic_duplicate_canary_id": "A document Canary identifier is duplicated.",
    "semantic_duplicate_fragment_id": "A protected fragment identifier is duplicated.",
    "semantic_evidence_id_reused": "An evidence identifier is reused in the corpus.",
    "semantic_fragment_roles_mismatch": "Protected fragment roles differ from the source document roles.",
    "semantic_unknown_scenario_subject": "A scenario references an unknown synthetic subject.",
    "semantic_unknown_scenario_target": "A scenario references an unknown document.",
    "semantic_unknown_scenario_evidence": "A scenario references unknown forbidden evidence.",
    "semantic_qa_document_coverage": "Authorized QA must cover each document exactly once.",
    "semantic_qa_subject_unauthorized": "The authorized QA subject cannot access its target document.",
    "semantic_qa_positive_assertion_required": "Authorized QA requires a positive fact assertion.",
    "semantic_qa_must_include_unanchored": "A required QA assertion is not anchored in the target document.",
    "semantic_qa_any_of_unanchored": "No alternative QA assertion is anchored in the target document.",
    "semantic_cross_role_not_unauthorized": "A cross-role scenario has no target unauthorized for its subject.",
    "semantic_evidence_target_mismatch": "Forbidden evidence is unrelated to every declared target document.",
    "report_rate_numerator_mismatch": "A report rate numerator does not match scenario evidence.",
    "report_rate_denominator_mismatch": "A report rate denominator does not match the locked denominator.",
    "report_rate_value_mismatch": "A report rate value does not match its recomputed ratio.",
    "report_aggregate_mismatch": "A report attack aggregate does not match scenario evidence.",
    "report_summary_mismatch": "A report summary value does not match scenario evidence.",
    "report_prevention_stage_mismatch": "A prevention stage is inconsistent with the paired attack result.",
    "report_mode_failed_consistency": "A failed mode result has inconsistent failure semantics.",
    "report_mode_nonfailed_consistency": "A non-failed mode result has inconsistent completion semantics.",
    "report_baseline_blocked": "Baseline mode cannot return a blocked outcome.",
    "report_attack_judgment_mismatch": "An attack judgment is inconsistent with final returned leakage.",
    "report_qa_judgment_mismatch": "An authorized QA judgment is inconsistent with outcome and fact assertion.",
    "report_gate_definition_mismatch": "A gate operator or threshold differs from the locked definition.",
    "report_gate_actual_mismatch": "A gate actual value differs from recomputed evidence.",
    "report_gate_passed_mismatch": "A gate passed value differs from its locked comparison.",
    "report_overall_gate_mismatch": "The overall gate differs from all component gate booleans.",
    "report_portfolio_ineligible": "Portfolio eligibility is true without every required evidence condition.",
    "chat_baseline_blocked": "Baseline chat cannot return a blocked outcome.",
    "chat_block_reply_mismatch": "A guarded blocked response does not use the fixed safe reply.",
    "chat_answered_uses_block_reply": "An answered response cannot use the fixed blocked reply.",
    "run_progress_mismatch": "Evaluation progress is inconsistent with its state.",
    "run_completed_at_mismatch": "Evaluation completion time is inconsistent with its state.",
    "run_failure_code_mismatch": "Evaluation failure code is inconsistent with its state.",
    "error_catalog_read_error": "The error catalog could not be read safely.",
    "error_catalog_invalid": "The error catalog has an invalid closed definition.",
    "problem_unknown_code": "Problem Details references an unknown stable error code.",
    "problem_status_mismatch": "Problem Details status differs from the error catalog.",
    "problem_retryable_mismatch": "Problem Details retryability differs from the error catalog.",
    "problem_type_mismatch": "Problem Details type differs from the error catalog.",
}


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """A non-sensitive issue whose message is selected only by stable code."""

    code: str
    path: tuple[PathPart, ...]
    message: str

    @classmethod
    def create(cls, code: str, path: tuple[PathPart, ...]) -> "ValidationIssue":
        return cls(code=code, path=path, message=_MESSAGES[code])

    def as_dict(self) -> dict[str, object]:
        return {"code": self.code, "path": list(self.path), "message": self.message}


def stable_issue_order(issue: ValidationIssue) -> tuple[str, ...]:
    """Return a platform-independent ordering key without inspecting raw values."""

    return tuple(f"{type(part).__name__}:{part}" for part in issue.path) + (issue.code,)
