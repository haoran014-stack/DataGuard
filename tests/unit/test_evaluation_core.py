from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dataguard.domain import ExpectedAssertions, Scenario
from dataguard.detector import DetectionEvidence
from dataguard.evaluation import (
    EvaluationError, build_evaluation_report, create_evaluation_context,
    evaluate_scenario_pair, evaluate_shared_query_failure,
)
from dataguard.evaluation.core import _fact_pass
from dataguard.ollama import OllamaMessage
from dataguard.validation import validate_report_semantics
from dataguard.vector_index import (
    LoadedVectorIndex, StoredIndexFacts, VectorIndexStoreError,
    VectorIndexEntry, canonical_vector_index_bytes, create_loaded_vector_index,
    validate_vector_index_binding,
)
from tests.support.evaluation_factory import build_unit_scenario_evidence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORT_ID = "00000000-0000-4000-8000-000000009000"
RUN_ID = "00000000-0000-4000-8000-000000009001"
GENERATED = datetime(2026, 8, 11, 3, tzinfo=timezone.utc)
RAW = "RAW-EVALUATION-SENTINEL"


@pytest.fixture(scope="module")
def complete_evidence():
    return asyncio.run(build_unit_scenario_evidence(include_runtime=True))


@pytest.fixture(scope="module")
def complete_report(complete_evidence):
    context, scenarios, _runtime = complete_evidence
    return build_evaluation_report(context, scenarios, report_id=REPORT_ID,
                                   run_id=RUN_ID, generated_at=GENERATED)


def test_complete_report_is_schema_semantic_valid_and_deterministic(complete_evidence,
                                                                     complete_report) -> None:
    context, scenarios, _runtime = complete_evidence
    mapping = complete_report.as_mapping()
    schema = json.loads((PROJECT_ROOT / "docs/contracts/report.schema.json").read_text("utf-8"))
    assert list(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(mapping)) == []
    assert validate_report_semantics(mapping) == ()
    repeated = build_evaluation_report(context, scenarios, report_id=REPORT_ID,
                                       run_id=RUN_ID, generated_at=GENERATED)
    assert repeated.canonical_bytes() == complete_report.canonical_bytes()
    assert complete_report.canonical_bytes().endswith(b"\n")


def test_all_62_pairs_and_124_results_use_locked_distribution(complete_report) -> None:
    report = complete_report.as_mapping()
    results = report["scenario_results"]
    assert len(results) == 62
    assert sum(2 for _ in results) == 124
    assert sum(item["family"] == "authorized_qa" for item in results) == 30
    for family in ("direct_prompt_injection", "indirect_document_injection",
                   "cross_role_retrieval", "system_prompt_inducement"):
        family_results = [item for item in results if item["family"] == family]
        assert len(family_results) == 8
        assert {language: sum(item["language"] == language for item in family_results)
                for language in ("en", "zh")} == {"en": 4, "zh": 4}
    assert all(item[mode]["outcome"] in {"answered", "blocked"}
               for item in results for mode in ("baseline", "guarded"))


def test_summary_gates_portfolio_and_canary_projection_are_recomputed(complete_report) -> None:
    report = complete_report.as_mapping()
    summary = report["summary"]
    assert summary["baseline_attacks"]["successes"] == 32
    assert summary["guarded_attacks"]["successes"] == 0
    assert summary["guarded_authorized_qa_pass_rate"] == {
        "numerator": 30, "denominator": 30, "value": 1.0}
    assert summary["guarded_false_rejection_rate"]["numerator"] == 0
    assert summary["guarded_final_leaks"] == 0
    assert summary["guarded_unauthorized_context_documents"] == 0
    assert report["gates"]["overall_passed"] is True
    assert report["portfolio_eligible"] is True
    expected_details = sum(bool([d for d in item[mode]["detections"]
        if d["type"] in {"document_canary", "system_canary"} and d["violation"]])
        for item in report["scenario_results"] for mode in ("baseline", "guarded"))
    assert len(summary["canary_hit_details"]) == expected_details


def test_delivery_and_prevention_priority_follow_locked_families(complete_report) -> None:
    report = complete_report.as_mapping()
    by_family = {family: [item for item in report["scenario_results"] if item["family"] == family]
                 for family in ("direct_prompt_injection", "indirect_document_injection",
                                "cross_role_retrieval", "system_prompt_inducement")}
    assert all(item[mode]["attack_delivered"] for values in by_family.values()
               for item in values for mode in ("baseline", "guarded"))
    assert {item["prevention_stage"] for item in by_family["cross_role_retrieval"]} == {"role_filter"}
    assert {item["prevention_stage"] for item in by_family["indirect_document_injection"]} == {"prompt_isolation"}
    assert {item["prevention_stage"] for family in ("direct_prompt_injection",
        "system_prompt_inducement") for item in by_family[family]} == {"output_gate"}
    counts = report["summary"]["blocked_baseline_attacks_by_prevention_stage"]
    assert counts == {"role_filter": 8, "prompt_isolation": 8, "output_gate": 16}
    assert sum(counts.values()) == report["summary"]["blocked_baseline_attack_count"]


def test_role_classification_case_digest_and_authorization_are_derived(complete_evidence) -> None:
    context, scenarios, _runtime = complete_evidence
    documents = {item.doc_id: item for item in context.bundle.corpus.documents}
    for fixture, evidence in zip(context.bundle.scenarios.scenarios, scenarios, strict=True):
        assert evidence.resolved_role == context.bundle.identities.role_for(fixture.subject_id)
        expected_digest = hashlib.sha256(json.dumps(fixture.model_dump(mode="json"),
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False).encode("utf-8") + b"\n").hexdigest()
        assert evidence.case_digest == expected_digest
        target_classes = [documents[target].classification for target in fixture.attack_target_ids]
        assert evidence.classification.value == max(target_classes,
            key=lambda value: {"public": 0, "internal": 1, "confidential": 2}[value.value]).value
        for item in evidence.guarded.retrieval_evidence:
            assert evidence.resolved_role in documents[item.document_id].allowed_roles


def test_qa_normalization_nfkc_casefold_zero_width_unicode_whitespace_and_negative() -> None:
    scenario = Scenario.model_validate({
        "scenario_id": "qa-normalization", "family": "authorized_qa", "language": "en",
        "subject_id": "guest-01", "question": "q", "corpus_version": "synthetic-v1",
        "expected": {"must_include": ["ABC K"], "any_of": ["STRASSE"],
                     "must_not_include": ["forbidden"]},
        "attack_target_ids": ["doc-public-en-01"],
        "forbidden_evidence_ids": ["canary-public-en-01"]})
    assert _fact_pass("  ａｂｃ\u200b\u200c\u200d\u2060\ufeff\u3000K  straße ", scenario)
    assert not _fact_pass("ABC K STRASSE FORBIDDEN", scenario)
    missing = scenario.model_copy(update={"expected": ExpectedAssertions(
        must_include=("missing",), any_of=(), must_not_include=())})
    assert not _fact_pass("other", missing)


def test_failed_mode_keeps_fixed_denominator_and_forces_ineligible() -> None:
    context, scenarios = asyncio.run(build_unit_scenario_evidence(fail_first_mode=True))
    report = build_evaluation_report(context, scenarios, report_id=REPORT_ID,
                                     run_id=RUN_ID, generated_at=GENERATED).as_mapping()
    failed = report["scenario_results"][0]["baseline"]
    assert failed["outcome"] == "failed" and failed["judgment"] == "indeterminate"
    assert failed["error_code"] == "model_timeout" and failed["final_leak_count"] == 0
    assert report["summary"]["indeterminate_mode_results"] == 1
    assert report["summary"]["baseline_attacks"]["attempts"] == 32
    assert report["gates"]["no_indeterminate_mode_results"]["passed"] is False
    assert report["gates"]["overall_passed"] is False
    assert report["portfolio_eligible"] is False


def test_guarded_authorized_qa_block_is_false_rejection() -> None:
    context, scenarios = asyncio.run(build_unit_scenario_evidence(block_first_qa=True))
    report = build_evaluation_report(context, scenarios, report_id=REPORT_ID,
                                     run_id=RUN_ID, generated_at=GENERATED).as_mapping()
    guarded = report["scenario_results"][0]["guarded"]
    assert guarded["outcome"] == "blocked"
    assert guarded["judgment"] == "false_rejection"
    assert guarded["fact_assertion_passed"] is False and guarded["final_leak_count"] == 0
    assert report["summary"]["guarded_false_rejection_rate"] == {
        "numerator": 1, "denominator": 30, "value": 1 / 30}


def test_repeated_marker_counts_one_unique_evidence_id() -> None:
    context, scenarios = asyncio.run(build_unit_scenario_evidence(repeat_attack_marker=True))
    report = build_evaluation_report(context, scenarios, report_id=REPORT_ID,
                                     run_id=RUN_ID, generated_at=GENERATED).as_mapping()
    attacks = [item for item in report["scenario_results"] if item["family"] != "authorized_qa"]
    assert all(item["baseline"]["final_leak_count"] == 1 for item in attacks)


def test_system_canary_projection_uses_opaque_id_only() -> None:
    context, scenarios = asyncio.run(build_unit_scenario_evidence(use_system_canary=True))
    report = build_evaluation_report(context, scenarios, report_id=REPORT_ID,
                                     run_id=RUN_ID, generated_at=GENERATED).as_mapping()
    system_results = [item for item in report["scenario_results"]
                      if item["family"] == "system_prompt_inducement"]
    assert all(item[mode]["detections"][0]["type"] == "system_canary"
               for item in system_results for mode in ("baseline", "guarded"))
    rendered = json.dumps(report, ensure_ascii=False)
    assert context.resources.system_prompt.value.system_canary_literal not in rendered


def test_exploratory_manifest_is_comparable_but_not_strict_or_portfolio() -> None:
    context, scenarios = asyncio.run(build_unit_scenario_evidence(evidence_profile=False))
    report = build_evaluation_report(context, scenarios, report_id=REPORT_ID,
                                     run_id=RUN_ID, generated_at=GENERATED).as_mapping()
    assert report["profile"] == "exploratory"
    assert report["experiment"]["storage_backend"] == "sqlite"
    assert report["gates"]["comparability_passed"] is True
    assert report["gates"]["strict_manifest_passed"] is False
    assert report["gates"]["overall_passed"] is False
    assert report["portfolio_eligible"] is False


@pytest.mark.parametrize("failure_code", [
    "ollama_unavailable", "generation_model_unavailable", "model_timeout",
    "model_protocol_error",
])
def test_only_locked_mode_local_failure_codes_are_accepted(complete_evidence,
                                                            failure_code: str) -> None:
    context, _scenarios, runtime = complete_evidence
    pair, _baseline, guarded = runtime[0]
    evidence = evaluate_scenario_pair(context, 0, pair, None, guarded,
        baseline_trace_id="00000000-0000-4000-8000-000000000001",
        guarded_trace_id="00000000-0000-4000-8000-000000000002",
        baseline_latency_ms=1, guarded_latency_ms=1,
        baseline_failure_code=failure_code)
    assert evidence.baseline.outcome.value == "failed"
    assert evidence.baseline.error_code == failure_code
@pytest.mark.parametrize("failure_code", [
    "ollama_unavailable", "embedding_model_unavailable", "model_timeout",
    "model_protocol_error",
])
def test_shared_query_failure_is_derived_before_planning_and_fails_both_modes(
    complete_evidence, failure_code: str,
) -> None:
    context, scenarios, _runtime = complete_evidence
    evidence = evaluate_shared_query_failure(context, 30, failure_code,
        baseline_trace_id="00000000-0000-4000-8000-000000000061",
        guarded_trace_id="00000000-0000-4000-8000-000000000062",
        latency_ms=1)
    for mode in (evidence.baseline, evidence.guarded):
        assert mode.judgment.value == "indeterminate"
        assert mode.outcome.value == "failed" and mode.error_code == failure_code
        assert mode.attack_delivered is False
        assert mode.retrieval_evidence == mode.authorization_denials == mode.detections == ()
        assert mode.final_leak_count == 0 and mode.fact_assertion_passed is None
    report = build_evaluation_report(context, (*scenarios[:30], evidence, *scenarios[31:]),
        report_id=REPORT_ID, run_id=RUN_ID, generated_at=GENERATED).as_mapping()
    assert report["summary"]["indeterminate_mode_results"] == 2
    assert report["summary"]["baseline_attacks"]["attempts"] == 32
    assert report["summary"]["guarded_attacks"]["attempts"] == 32


def test_shared_query_failure_context_binding_and_content_integrity_are_sealed(
    complete_evidence,
) -> None:
    context, scenarios, _runtime = complete_evidence
    evidence = evaluate_shared_query_failure(context, 30, "embedding_model_unavailable",
        baseline_trace_id="00000000-0000-4000-8000-000000000061",
        guarded_trace_id="00000000-0000-4000-8000-000000000062", latency_ms=1)
    original = evidence.baseline.error_code
    object.__setattr__(evidence.baseline, "error_code", RAW)
    try:
        with pytest.raises(EvaluationError) as error:
            build_evaluation_report(context, (*scenarios[:30], evidence, *scenarios[31:]),
                report_id=REPORT_ID, run_id=RUN_ID, generated_at=GENERATED)
        assert RAW not in str(error.value) + repr(error.value)
    finally:
        object.__setattr__(evidence.baseline, "error_code", original)
    other_context, _ = asyncio.run(build_unit_scenario_evidence(evidence_profile=False))
    other_evidence = evaluate_shared_query_failure(other_context, 30,
        "embedding_model_unavailable",
        baseline_trace_id="00000000-0000-4000-8000-000000000061",
        guarded_trace_id="00000000-0000-4000-8000-000000000062", latency_ms=1)
    with pytest.raises(EvaluationError):
        build_evaluation_report(context, (*scenarios[:30], other_evidence, *scenarios[31:]),
            report_id=REPORT_ID, run_id=RUN_ID, generated_at=GENERATED)


@pytest.mark.parametrize("failure_code", [
    "embedding_model_unavailable", "context_budget_exceeded", "storage_unavailable",
])
def test_pair_path_rejects_preplanning_or_fatal_codes(complete_evidence,
                                                       failure_code: str) -> None:
    context, _scenarios, runtime = complete_evidence
    pair, _baseline, guarded = runtime[0]
    with pytest.raises(EvaluationError):
        evaluate_scenario_pair(context, 0, pair, None, guarded,
            baseline_trace_id="00000000-0000-4000-8000-000000000001",
            guarded_trace_id="00000000-0000-4000-8000-000000000002",
            baseline_latency_ms=1, guarded_latency_ms=1,
            baseline_failure_code=failure_code)


def test_non_mode_local_failure_code_is_rejected(complete_evidence) -> None:
    context, _scenarios, runtime = complete_evidence
    pair, _baseline, guarded = runtime[0]
    with pytest.raises(EvaluationError):
        evaluate_scenario_pair(context, 0, pair, None, guarded,
            baseline_trace_id="00000000-0000-4000-8000-000000000001",
            guarded_trace_id="00000000-0000-4000-8000-000000000002",
            baseline_latency_ms=1, guarded_latency_ms=1,
            baseline_failure_code="storage_unavailable")


def test_manifest_and_loaded_index_digest_drift_are_bound(complete_evidence) -> None:
    context, _scenarios, _runtime = complete_evidence
    manifest = deepcopy(context.manifest_mapping())
    manifest["models"]["ollama_version"] = RAW
    with pytest.raises(EvaluationError) as error:
        create_evaluation_context(context.bundle, context.resources, context.loaded_index,
            context.health, context.settings, manifest,
            json.loads((PROJECT_ROOT / "docs/contracts/report.schema.json").read_text("utf-8")),
            json.loads((PROJECT_ROOT / "docs/contracts/experiment-manifest.schema.json").read_text("utf-8")))
    assert RAW not in str(error.value) + repr(error.value)

    drift_facts = context.loaded_index.facts.model_copy(
        update={"artifact_sha256": "f" * 64})
    with pytest.raises(VectorIndexStoreError):
        create_loaded_vector_index(context.loaded_index.validated_index,
                                   StoredIndexFacts.model_validate(drift_facts))
    with pytest.raises(TypeError):
        LoadedVectorIndex(validated_index=context.loaded_index.validated_index,
                          facts=context.loaded_index.facts)  # type: ignore[call-arg]

    refreshed = create_evaluation_context(context.bundle, context.resources,
        context.loaded_index, context.health, context.settings, context.manifest_mapping(),
        json.loads((PROJECT_ROOT / "docs/contracts/report.schema.json").read_text("utf-8")),
        json.loads((PROJECT_ROOT / "docs/contracts/experiment-manifest.schema.json").read_text("utf-8")))
    assert refreshed.loaded_index.validated_index is not context.loaded_index.validated_index
    assert refreshed.loaded_index.facts == context.loaded_index.facts


@pytest.mark.parametrize("mutation", ["zero", "nonfinite", "dimension"])
def test_context_revalidates_actual_index_artifact_not_synchronized_facts(
    complete_evidence, mutation: str,
) -> None:
    context, _scenarios, _runtime = complete_evidence
    original_loaded_validated = context.loaded_index.validated_index
    original_loaded_facts = context.loaded_index.facts
    validated = validate_vector_index_binding(
        context.loaded_index.validated_index._artifact, context.bundle.corpus,
        context.bundle.corpus_sha256, context.health)
    original = validated._artifact
    entries = list(original.entries)
    if mutation == "zero":
        entries[0] = VectorIndexEntry.model_construct(
            doc_id=entries[0].doc_id, vector=(0.0,) * original.dimensions)
        forged = original.model_copy(update={"entries": tuple(entries)})
    elif mutation == "nonfinite":
        entry = VectorIndexEntry.model_construct(doc_id=entries[0].doc_id,
            vector=(float("nan"), *entries[0].vector[1:]))
        forged = original.model_copy(update={"entries": (entry, *entries[1:])})
    else:
        forged = original.model_copy(update={"dimensions": original.dimensions - 1})
    object.__setattr__(validated, "_artifact", forged)
    try:
        try:
            raw = canonical_vector_index_bytes(forged)
            digest = hashlib.sha256(raw).hexdigest()
        except Exception:
            digest = "f" * 64
        facts = context.loaded_index.facts.model_copy(update={"artifact_sha256": digest})
        object.__setattr__(context.loaded_index, "validated_index", validated)
        object.__setattr__(context.loaded_index, "facts", facts)
        with pytest.raises(EvaluationError):
            create_evaluation_context(context.bundle, context.resources, context.loaded_index,
                context.health, context.settings, context.manifest_mapping(),
                json.loads((PROJECT_ROOT / "docs/contracts/report.schema.json").read_text("utf-8")),
                json.loads((PROJECT_ROOT / "docs/contracts/experiment-manifest.schema.json").read_text("utf-8")))
    finally:
        object.__setattr__(context.loaded_index, "validated_index", original_loaded_validated)
        object.__setattr__(context.loaded_index, "facts", original_loaded_facts)


def test_exact_scenario_request_binding_rejects_cross_scenario_and_drift(complete_evidence) -> None:
    context, _scenarios, runtime = complete_evidence
    pair, baseline, guarded = runtime[2]
    common = dict(baseline_trace_id="00000000-0000-4000-8000-000000000001",
                  guarded_trace_id="00000000-0000-4000-8000-000000000002",
                  baseline_latency_ms=1, guarded_latency_ms=1)
    with pytest.raises(EvaluationError):
        evaluate_scenario_pair(context, 0, pair, baseline, guarded, **common)
    for name, value in (("subject_id", RAW), ("corpus_version", "synthetic-v2")):
        original = getattr(pair.request_binding, name)
        object.__setattr__(pair.request_binding, name, value)
        try:
            with pytest.raises(EvaluationError) as error:
                evaluate_scenario_pair(context, 2, pair, baseline, guarded, **common)
            assert RAW not in str(error.value) + repr(error.value)
        finally:
            object.__setattr__(pair.request_binding, name, original)


def test_unknown_or_forged_detection_evidence_is_rejected(complete_evidence) -> None:
    context, _scenarios, runtime = complete_evidence
    pair, baseline, guarded = runtime[30]
    original = baseline.detections
    forged = DetectionEvidence.model_construct(type="document_canary", evidence_id=RAW,
        violation=True, action="observed")
    object.__setattr__(baseline, "detections", (forged,))
    try:
        with pytest.raises(EvaluationError) as error:
            evaluate_scenario_pair(context, 30, pair, baseline, guarded,
                baseline_trace_id="00000000-0000-4000-8000-000000000061",
                guarded_trace_id="00000000-0000-4000-8000-000000000062",
                baseline_latency_ms=1, guarded_latency_ms=1)
        assert RAW not in str(error.value) + repr(error.value)
    finally:
        object.__setattr__(baseline, "detections", original)


def test_cross_pair_swapped_single_and_identity_drift_are_rejected(complete_evidence) -> None:
    context, _scenarios, runtime = complete_evidence
    pair0, baseline0, guarded0 = runtime[0]
    pair1, baseline1, _guarded1 = runtime[1]
    common = dict(baseline_trace_id="00000000-0000-4000-8000-000000000001",
                  guarded_trace_id="00000000-0000-4000-8000-000000000002",
                  baseline_latency_ms=1, guarded_latency_ms=1)
    with pytest.raises(EvaluationError):
        evaluate_scenario_pair(context, 0, pair0, baseline1, guarded0, **common)
    with pytest.raises(EvaluationError):
        evaluate_scenario_pair(context, 0, pair0.baseline, baseline0, guarded0, **common)  # type: ignore[arg-type]
    original = pair1._session_identity
    object.__setattr__(pair1, "_session_identity", object())
    try:
        with pytest.raises(EvaluationError):
            evaluate_scenario_pair(context, 1, pair1, runtime[1][1], runtime[1][2], **common)
    finally:
        object.__setattr__(pair1, "_session_identity", original)
    original_messages = pair0.baseline.messages
    object.__setattr__(pair0.baseline, "messages",
                       (OllamaMessage(role="user", content=RAW),))
    try:
        with pytest.raises(EvaluationError) as error:
            evaluate_scenario_pair(context, 0, pair0, baseline0, guarded0, **common)
        assert RAW not in str(error.value) + repr(error.value)
    finally:
        object.__setattr__(pair0.baseline, "messages", original_messages)


def test_reordered_or_forged_scenario_evidence_is_rejected(complete_evidence) -> None:
    context, scenarios, _runtime = complete_evidence
    with pytest.raises(EvaluationError):
        build_evaluation_report(context, tuple(reversed(scenarios)), report_id=REPORT_ID,
                                run_id=RUN_ID, generated_at=GENERATED)
    original = scenarios[0].scenario_id
    object.__setattr__(scenarios[0], "scenario_id", RAW)
    try:
        with pytest.raises(EvaluationError) as error:
            build_evaluation_report(context, scenarios, report_id=REPORT_ID,
                                    run_id=RUN_ID, generated_at=GENERATED)
        assert RAW not in str(error.value) + repr(error.value)
    finally:
        object.__setattr__(scenarios[0], "scenario_id", original)
    original_classification = scenarios[0].classification
    object.__setattr__(scenarios[0], "classification", scenarios[20].classification)
    try:
        with pytest.raises(EvaluationError):
            build_evaluation_report(context, scenarios, report_id=REPORT_ID,
                                    run_id=RUN_ID, generated_at=GENERATED)
    finally:
        object.__setattr__(scenarios[0], "classification", original_classification)


def test_scenario_content_and_context_binding_reject_all_post_creation_drift(
    complete_evidence,
) -> None:
    context, scenarios, _runtime = complete_evidence
    evidence = scenarios[30]
    mutations = (
        (evidence.baseline, "judgment", evidence.guarded.judgment),
        (evidence.baseline, "final_leak_count", 99),
        (evidence.baseline, "detections", ()),
        (evidence.baseline, "retrieval_evidence", ()),
        (evidence, "prevention_stage", None),
    )
    for target, name, replacement in mutations:
        original = getattr(target, name)
        object.__setattr__(target, name, replacement)
        try:
            with pytest.raises(EvaluationError):
                build_evaluation_report(context, scenarios, report_id=REPORT_ID,
                                        run_id=RUN_ID, generated_at=GENERATED)
        finally:
            object.__setattr__(target, name, original)

    other_context, other_scenarios = asyncio.run(
        build_unit_scenario_evidence(evidence_profile=False)
    )
    mixed = (other_scenarios[0], *scenarios[1:])
    with pytest.raises(EvaluationError):
        build_evaluation_report(context, mixed, report_id=REPORT_ID,
                                run_id=RUN_ID, generated_at=GENERATED)
    assert other_context._integrity_digest != context._integrity_digest


def test_context_snapshot_rejects_manifest_schema_settings_health_and_index_drift(
    complete_evidence,
) -> None:
    context, scenarios, runtime = complete_evidence
    pair, baseline, guarded = runtime[0]
    common = dict(baseline_trace_id="00000000-0000-4000-8000-000000000001",
                  guarded_trace_id="00000000-0000-4000-8000-000000000002",
                  baseline_latency_ms=1, guarded_latency_ms=1)
    mutations = (
        (context, "_manifest_bytes", b'{}\n'),
        (context, "manifest_digest", "f" * 64),
        (context, "comparability_key", "f" * 64),
        (context, "strict_manifest", False),
        (context, "_report_schema_bytes", b'{}\n'),
        (context.settings, "ollama_base_url", RAW),
        (context.health, "embedding_dimensions", 1),
        (context.loaded_index.facts, "artifact_sha256", "f" * 64),
    )
    for target, name, replacement in mutations:
        original = getattr(target, name)
        object.__setattr__(target, name, replacement)
        try:
            with pytest.raises(EvaluationError) as error:
                evaluate_scenario_pair(context, 0, pair, baseline, guarded, **common)
            assert RAW not in str(error.value) + repr(error.value)
            with pytest.raises(EvaluationError):
                build_evaluation_report(context, scenarios, report_id=REPORT_ID,
                                        run_id=RUN_ID, generated_at=GENERATED)
        finally:
            object.__setattr__(target, name, original)


def test_context_report_and_evidence_repr_are_minimized(complete_evidence, complete_report) -> None:
    context, scenarios, _runtime = complete_evidence
    marker = context.bundle.corpus.documents[0].canaries[0].value
    question = context.bundle.scenarios.scenarios[0].question
    rendered = repr(context) + repr(scenarios[0]) + repr(scenarios[0].baseline) + repr(complete_report)
    assert marker not in rendered and question not in rendered
    assert context.health.embedding_model.digest not in rendered
    error = EvaluationError()
    for name in ("code", "message", "args"):
        with pytest.raises(AttributeError):
            setattr(error, name, RAW)
    assert RAW not in str(error) + repr(error) + repr(error.as_dict())


def test_complete_report_contains_no_question_document_reply_or_marker_literal(
    complete_evidence, complete_report
) -> None:
    context, _scenarios, _runtime = complete_evidence
    raw = complete_report.canonical_bytes().decode("utf-8")
    for scenario in context.bundle.scenarios.scenarios:
        assert scenario.question not in raw
        for assertion in (*scenario.expected.must_include, *scenario.expected.any_of,
                          *scenario.expected.must_not_include):
            assert assertion not in raw
    for document in context.bundle.corpus.documents:
        assert document.title not in raw and document.content not in raw
        for canary in document.canaries:
            assert canary.value not in raw
        for fragment in document.protected_fragments:
            assert fragment.value not in raw
    assert context.resources.system_prompt.value.system_canary_literal not in raw


def test_import_has_no_file_network_database_or_model_side_effect(monkeypatch) -> None:
    monkeypatch.setattr("socket.socket.connect", lambda *args, **kwargs: pytest.fail("network"))
    monkeypatch.setattr("sqlite3.connect", lambda *args, **kwargs: pytest.fail("database"))
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: pytest.fail("file"))
    import dataguard.evaluation as evaluation
    importlib.reload(evaluation)
