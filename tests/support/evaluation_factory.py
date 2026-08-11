"""Unit-only deterministic evidence simulator; never a runtime or measurement path."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from dataguard.config import RuntimeSettings
from dataguard.detector import build_whole_output_detector
from dataguard.domain import ScenarioFamily
from dataguard.evaluation import create_evaluation_context, evaluate_scenario_pair
from dataguard.ollama import OllamaClient, OllamaHealthFacts, OllamaModelFacts
from dataguard.rag import create_rag_executor, create_rag_planner, embed_query
from dataguard.resources import load_security_resources
from dataguard.validation import load_fixture_bundle
from dataguard.vector_index import (
    StoredIndexFacts, VECTOR_INDEX_FORMAT, VectorIndexArtifact,
    VectorIndexEntry, canonical_vector_index_bytes, validate_vector_index_binding,
    create_loaded_vector_index,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GENERATION_DIGEST = "a" * 64
EMBEDDING_DIGEST = "b" * 64
DIMENSIONS = 30


def _health() -> OllamaHealthFacts:
    return OllamaHealthFacts(version="unit-only-1.0",
        generation_model=OllamaModelFacts(tag="qwen2.5:3b-instruct", digest=GENERATION_DIGEST),
        embedding_model=OllamaModelFacts(tag="qwen3-embedding:0.6b", digest=EMBEDDING_DIGEST),
        embedding_dimensions=DIMENSIONS)


def _manifest(bundle, resources, index_digest: str, settings: RuntimeSettings) -> dict[str, Any]:
    digests = resources.artifact_digests()
    return {
        "manifest_version": "1.0", "synthetic": True,
        "corpus_version": "synthetic-v1", "scenario_set_version": "synthetic-v1",
        "created_at": "2026-08-11T03:00:00Z", "profile": settings.profile.value,
        "storage_backend": settings.storage_backend.value,
        "distribution": {
            "identities": {"total": 6, "by_role": {"guest": 2, "employee": 2, "security_reviewer": 2}},
            "documents": {"total": 30, "by_classification_and_language": {
                key: {"total": 10, "en": 5, "zh": 5}
                for key in ("public", "internal", "confidential")}},
            "scenarios": {"total": 62,
                "authorized_qa": {"total": 30, "one_per_document": True},
                "attacks": {"total": 32, "by_family": {
                    key: {"total": 8, "en": 4, "zh": 4}
                    for key in ("direct_prompt_injection", "indirect_document_injection",
                                "cross_role_retrieval", "system_prompt_inducement")}}},
        },
        "models": {"ollama_version": _health().version,
            "generation": {"tag": "qwen2.5:3b-instruct", "digest": GENERATION_DIGEST},
            "embedding": {"tag": "qwen3-embedding:0.6b", "digest": EMBEDDING_DIGEST,
                          "embedding_dimensions": DIMENSIONS}},
        "settings": resources.guard_policy.value.settings.model_dump(mode="json"),
        "system_prompt": {
            "system_canary_evidence_id": str(resources.system_prompt.value.system_canary_evidence_id),
            "content_digest": resources.system_prompt.sha256},
        "detector": {"version": resources.detector.value.version,
            "normalization": list(resources.detector.value.normalization),
            "detection_types": list(resources.detector.value.detection_types),
            "guarded_block_reply": resources.detector.value.guarded_fixed_reply},
        "artifact_digests": {
            "identity_table": bundle.identity_sha256, "corpus": bundle.corpus_sha256,
            "scenario_set": bundle.scenario_sha256, "vector_index": index_digest,
            "baseline_prompt_template": digests["baseline_prompt_template"],
            "guarded_prompt_template": digests["guarded_prompt_template"],
            "guard_policy": digests["guard_policy"], "detector": digests["detector"]},
    }


def _marker_values(bundle) -> dict[str, str]:
    values: dict[str, str] = {}
    for document in bundle.corpus.documents:
        values.update({item.canary_id: item.value for item in document.canaries})
        values.update({item.fragment_id: item.value for item in document.protected_fragments})
    return values


async def build_unit_scenario_evidence(*, evidence_profile: bool = True,
                                       fail_first_mode: bool = False,
                                       block_first_qa: bool = False,
                                       repeat_attack_marker: bool = False,
                                       use_system_canary: bool = False,
                                       include_runtime: bool = False):
    loaded = load_fixture_bundle(PROJECT_ROOT)
    assert loaded.ok and loaded.bundle is not None
    bundle = loaded.bundle
    resources = load_security_resources()
    health = _health()
    ids = tuple(document.doc_id for document in bundle.corpus.documents)
    entries = tuple(VectorIndexEntry(doc_id=doc_id,
        vector=tuple(1.0 if row == column else 0.0 for column in range(DIMENSIONS)))
        for row, doc_id in enumerate(ids))
    artifact = VectorIndexArtifact(format=VECTOR_INDEX_FORMAT,
        corpus_version="synthetic-v1", corpus_sha256=bundle.corpus_sha256,
        ordered_document_ids=ids, embedding_model_tag=health.embedding_model.tag,
        embedding_model_digest=health.embedding_model.digest, dimensions=DIMENSIONS,
        entries=entries)
    raw_index = canonical_vector_index_bytes(artifact)
    index_digest = hashlib.sha256(raw_index).hexdigest()
    validated = validate_vector_index_binding(artifact, bundle.corpus,
                                               bundle.corpus_sha256, health)
    loaded_index = create_loaded_vector_index(validated,
        StoredIndexFacts(artifact_sha256=index_digest, format=VECTOR_INDEX_FORMAT,
                         document_count=30, dimensions=DIMENSIONS))
    settings = (RuntimeSettings(profile="evidence", storage_backend="postgresql",
                    database_dsn="postgresql+psycopg://localhost/dataguard")
                if evidence_profile else RuntimeSettings())
    report_schema = json.loads((PROJECT_ROOT / "docs/contracts/report.schema.json").read_text("utf-8"))
    manifest_schema = json.loads((PROJECT_ROOT / "docs/contracts/experiment-manifest.schema.json").read_text("utf-8"))
    context = create_evaluation_context(bundle, resources, loaded_index, health, settings,
        _manifest(bundle, resources, index_digest, settings), report_schema, manifest_schema)
    planner = create_rag_planner(bundle.identities, bundle.corpus, bundle.corpus_sha256,
                                 resources, context.loaded_index.validated_index)
    detector = build_whole_output_detector(resources, bundle.corpus)
    markers = _marker_values(bundle)
    state: dict[str, Any] = {"target": 0, "output": "unit safe response"}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/embed":
            vector = [1.0 if index == state["target"] else 0.0 for index in range(DIMENSIONS)]
            return httpx.Response(200, json={"model": "qwen3-embedding:0.6b",
                "embeddings": [vector]}, headers={"Content-Type": "application/json"})
        return httpx.Response(200, json={"model": "qwen2.5:3b-instruct",
            "message": {"role": "assistant", "content": state["output"]}, "done": True},
            headers={"Content-Type": "application/json"})

    scenario_evidence = []
    runtime_records = []
    async with OllamaClient(RuntimeSettings(), transport=httpx.MockTransport(handler)) as client:
        executor = create_rag_executor(client, detector)
        for index, scenario in enumerate(bundle.scenarios.scenarios):
            target_id = scenario.attack_target_ids[0]
            state["target"] = ids.index(target_id)
            query = await embed_query(scenario.question, health, client)
            pair = await planner.plan_pair(corpus_version="synthetic-v1",
                subject_id=scenario.subject_id, question=scenario.question,
                query_embedding=query)
            if scenario.family is ScenarioFamily.AUTHORIZED_QA:
                state["output"] = " ".join((*scenario.expected.must_include,
                    *(scenario.expected.any_of[:1])))
            else:
                marker = (resources.system_prompt.value.system_canary_literal
                    if use_system_canary and scenario.family is ScenarioFamily.SYSTEM_PROMPT_INDUCEMENT
                    else markers[scenario.forbidden_evidence_ids[0]])
                state["output"] = marker + (" " + marker if repeat_attack_marker else "")
            baseline = await executor.execute(pair.baseline)
            guarded_failure = None
            if scenario.family in {ScenarioFamily.DIRECT_PROMPT_INJECTION,
                                   ScenarioFamily.SYSTEM_PROMPT_INDUCEMENT}:
                state["output"] = (resources.system_prompt.value.system_canary_literal
                    if use_system_canary and scenario.family is ScenarioFamily.SYSTEM_PROMPT_INDUCEMENT
                    else markers[scenario.forbidden_evidence_ids[0]])
            elif scenario.family is ScenarioFamily.AUTHORIZED_QA:
                state["output"] = (markers[scenario.forbidden_evidence_ids[0]]
                    if block_first_qa and index == 0 else
                    " ".join((*scenario.expected.must_include,
                              *(scenario.expected.any_of[:1]))))
            else:
                state["output"] = "unit safe response"
            guarded = await executor.execute(pair.guarded)
            baseline_failure = "model_timeout" if fail_first_mode and index == 0 else None
            scenario_evidence.append(evaluate_scenario_pair(context, index, pair,
                None if baseline_failure else baseline, guarded,
                baseline_trace_id=f"00000000-0000-4000-8000-{index * 2 + 1:012d}",
                guarded_trace_id=f"00000000-0000-4000-8000-{index * 2 + 2:012d}",
                baseline_latency_ms=index, guarded_latency_ms=index + 1,
                baseline_failure_code=baseline_failure,
                guarded_failure_code=guarded_failure))
            runtime_records.append((pair, baseline, guarded))
    if include_runtime:
        return context, tuple(scenario_evidence), tuple(runtime_records)
    return context, tuple(scenario_evidence)
