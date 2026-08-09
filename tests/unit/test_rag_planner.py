from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from dataguard.config import RuntimeSettings
from dataguard.domain import Corpus, Role
from dataguard.detector import WholeOutputDetector
from dataguard.ollama import OllamaClient, OllamaHealthFacts, OllamaMessage, OllamaModelFacts
from dataguard.ollama import OllamaAdapterError, OllamaErrorCode
from dataguard.ollama.client import EMBEDDING_MODEL, GENERATION_MODEL
from dataguard.rag import (
    QueryEmbedding,
    AuthorizationDenial,
    RagMode,
    RagPlanningError,
    RagPlanningErrorCode,
    canonical_documents_json,
    context_message_bytes,
    create_rag_planner,
    embed_query,
)
from dataguard.resources import ResourceArtifact, load_security_resources
from dataguard.validation import load_fixture_bundle
from dataguard.vector_index import (
    VECTOR_INDEX_FORMAT,
    RetrievalResult,
    VectorIndexArtifact,
    VectorIndexEntry,
    retrieve as actual_retrieve,
    validate_vector_index_binding,
)
from dataguard.vector_index.store import VectorIndexStore


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GENERATION_DIGEST = "a" * 64
EMBEDDING_DIGEST = "sha256:" + "b" * 64
RAW_SENTINEL = "RAG_RAW_SENTINEL_SHOULD_NOT_APPEAR"
DIMENSIONS = 3


def _run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


@pytest.fixture(scope="module")
def bundle():
    loaded = load_fixture_bundle(PROJECT_ROOT)
    assert loaded.ok and loaded.bundle is not None
    return loaded.bundle


@pytest.fixture(scope="module")
def security_resources():
    return load_security_resources()


def _health(
    *,
    digest: str = EMBEDDING_DIGEST,
    dimensions: int = DIMENSIONS,
) -> OllamaHealthFacts:
    return OllamaHealthFacts(
        version="0.12.1",
        generation_model=OllamaModelFacts(
            tag=GENERATION_MODEL,
            digest=GENERATION_DIGEST,
        ),
        embedding_model=OllamaModelFacts(tag=EMBEDDING_MODEL, digest=digest),
        embedding_dimensions=dimensions,
    )


def _artifact(corpus: Corpus, corpus_sha256: str) -> VectorIndexArtifact:
    ids = tuple(document.doc_id for document in corpus.documents)
    vectors: list[tuple[float, float, float]] = []
    for position, document in enumerate(corpus.documents):
        if document.classification.value == "confidential":
            vectors.append((1.0, 0.001 * (position + 1), 0.0))
        elif document.classification.value == "internal":
            vectors.append((0.8, 0.001 * (position + 1), 0.1))
        else:
            vectors.append((0.6, 0.001 * (position + 1), 0.2))
    return VectorIndexArtifact(
        format=VECTOR_INDEX_FORMAT,
        corpus_version=corpus.corpus_version,
        corpus_sha256=corpus_sha256,
        ordered_document_ids=ids,
        embedding_model_tag=EMBEDDING_MODEL,
        embedding_model_digest=EMBEDDING_DIGEST,
        dimensions=DIMENSIONS,
        entries=tuple(
            VectorIndexEntry(doc_id=doc_id, vector=vector)
            for doc_id, vector in zip(ids, vectors, strict=True)
        ),
    )


def _index(corpus: Corpus, corpus_sha256: str):
    return validate_vector_index_binding(
        _artifact(corpus, corpus_sha256),
        corpus,
        corpus_sha256,
        _health(),
    )


async def _query(
    question: str,
    *,
    health: OllamaHealthFacts | None = None,
    observed: list[httpx.Request] | None = None,
) -> QueryEmbedding:
    facts = health or _health()

    async def handler(request: httpx.Request) -> httpx.Response:
        if observed is not None:
            observed.append(request)
        return httpx.Response(
            200,
            json={
                "model": EMBEDDING_MODEL,
                "embeddings": [[1.0, *([0.0] * (facts.embedding_dimensions - 1))]],
            },
            headers={"Content-Type": "application/json"},
        )

    async with OllamaClient(
        RuntimeSettings(), transport=httpx.MockTransport(handler)
    ) as client:
        return await embed_query(question, facts, client)


def _planner(bundle, security_resources):
    return create_rag_planner(
        bundle.identities,
        bundle.corpus,
        bundle.corpus_sha256,
        security_resources,
        _index(bundle.corpus, bundle.corpus_sha256),
    )


def _plan(planner, query, *, subject="guest-01", question="synthetic question", mode="baseline"):
    return _run(
        planner.plan(
            corpus_version="synthetic-v1",
            subject_id=subject,
            question=question,
            mode=mode,
            query_embedding=query,
        )
    )


def _assert_safe_error(error: RagPlanningError) -> None:
    rendered = " ".join((str(error), repr(error), repr(error.as_dict())))
    assert set(error.as_dict()) == {"code", "message"}
    assert RAW_SENTINEL not in rendered
    assert "DG_SYNTHETIC" not in rendered
    assert "http://" not in rendered


def test_query_embedding_uses_exact_whitespace_and_is_opaque_immutable() -> None:
    observed: list[httpx.Request] = []
    question = " \t\u3000\n"
    query = _run(_query(question, observed=observed))
    assert json.loads(observed[0].content) == {
        "model": EMBEDDING_MODEL,
        "input": [question],
        "truncate": False,
    }
    assert query.dimensions == DIMENSIONS
    assert query.embedding_model_tag == EMBEDDING_MODEL
    assert query.embedding_model_digest == EMBEDDING_DIGEST
    rendered = repr(query)
    assert question not in rendered and EMBEDDING_DIGEST not in rendered
    assert "1.0" not in rendered and "vector" not in rendered.lower()
    with pytest.raises(FrozenInstanceError):
        query._dimensions = 2  # type: ignore[misc]
    with pytest.raises(TypeError):
        QueryEmbedding((1.0, 0.0, 0.0), EMBEDDING_MODEL, EMBEDDING_DIGEST, 3, _token=object())


def test_query_embedding_propagates_content_safe_ollama_error_unchanged() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(RAW_SENTINEL, request=request)

    async def exercise() -> None:
        async with OllamaClient(
            RuntimeSettings(), transport=httpx.MockTransport(handler)
        ) as client:
            await embed_query(RAW_SENTINEL, _health(), client)

    with pytest.raises(OllamaAdapterError) as captured:
        _run(exercise())
    assert captured.value.code is OllamaErrorCode.OLLAMA_UNAVAILABLE
    assert RAW_SENTINEL not in str(captured.value) + repr(captured.value.as_dict())


def test_query_embedding_rejects_zero_vector_as_manifest_mismatch() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"model": EMBEDDING_MODEL, "embeddings": [[0.0, 0.0, 0.0]]},
            headers={"Content-Type": "application/json"},
        )

    async def exercise() -> None:
        async with OllamaClient(
            RuntimeSettings(), transport=httpx.MockTransport(handler)
        ) as client:
            await embed_query("synthetic", _health(), client)

    with pytest.raises(RagPlanningError) as captured:
        _run(exercise())
    assert captured.value.code is RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH


def test_query_embedding_revalidates_unchecked_health_before_transport() -> None:
    calls = 0
    malformed = _health().model_copy(update={"embedding_dimensions": 0})

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async def exercise() -> None:
        async with OllamaClient(
            RuntimeSettings(), transport=httpx.MockTransport(handler)
        ) as client:
            await embed_query("synthetic", malformed, client)

    with pytest.raises(RagPlanningError) as captured:
        _run(exercise())
    assert captured.value.code is RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH
    assert calls == 0


@pytest.mark.parametrize("question", ["", "x" * 2001, 1, None])
def test_query_embedding_rejects_public_question_bounds_without_transport(question: Any) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    async def exercise() -> None:
        async with OllamaClient(
            RuntimeSettings(), transport=httpx.MockTransport(handler)
        ) as client:
            await embed_query(question, _health(), client)  # type: ignore[arg-type]

    with pytest.raises(RagPlanningError) as captured:
        _run(exercise())
    assert captured.value.code is RagPlanningErrorCode.INVALID_REQUEST
    assert calls == 0


def test_planner_request_validation_order_and_not_found_reachability(bundle, security_resources) -> None:
    planner = _planner(bundle, security_resources)
    query = _run(_query("valid"))
    cases = [
        ({"corpus_version": " bad", "subject_id": "!bad"}, RagPlanningErrorCode.INVALID_REQUEST),
        ({"corpus_version": "synthetic-v2", "subject_id": "!bad"}, RagPlanningErrorCode.CORPUS_NOT_FOUND),
        ({"corpus_version": "synthetic-v1", "subject_id": "!bad"}, RagPlanningErrorCode.INVALID_REQUEST),
        ({"corpus_version": "synthetic-v1", "subject_id": "unknown:valid"}, RagPlanningErrorCode.SUBJECT_NOT_FOUND),
    ]
    for overrides, expected in cases:
        with pytest.raises(RagPlanningError) as captured:
            _run(
                planner.plan(
                    corpus_version=overrides["corpus_version"],
                    subject_id=overrides["subject_id"],
                    question=RAW_SENTINEL,
                    mode="baseline",
                    query_embedding=query,
                )
            )
        assert captured.value.code is expected
        _assert_safe_error(captured.value)


@pytest.mark.parametrize(
    ("subject", "role", "eligible_count", "denial_count"),
    [
        ("guest-01", Role.GUEST, 10, 20),
        ("employee-01", Role.EMPLOYEE, 20, 10),
        ("security_reviewer-01", Role.SECURITY_REVIEWER, 30, 0),
    ],
)
def test_guarded_prefilters_before_retrieval_for_all_roles(
    bundle,
    security_resources,
    monkeypatch,
    subject: str,
    role: Role,
    eligible_count: int,
    denial_count: int,
) -> None:
    planner = _planner(bundle, security_resources)
    query = _run(_query("authorized synthetic question"))
    observed_eligible: list[tuple[str, ...]] = []

    def spy(index, vector, eligible):
        observed_eligible.append(eligible)
        return actual_retrieve(index, vector, eligible)

    monkeypatch.setattr("dataguard.rag.planner.retrieve", spy)
    plan = _plan(
        planner,
        query,
        subject=subject,
        question="authorized synthetic question",
        mode="guarded",
    )
    expected = tuple(
        document.doc_id
        for document in bundle.corpus.documents
        if role in document.allowed_roles
    )
    assert observed_eligible == [expected]
    assert len(expected) == eligible_count
    assert plan.resolved_role is role
    assert len(plan.authorization_denials) == denial_count
    assert tuple(denial.doc_id for denial in plan.authorization_denials) == tuple(
        document.doc_id
        for document in bundle.corpus.documents
        if role not in document.allowed_roles
    )
    assert all(
        role in next(doc for doc in bundle.corpus.documents if doc.doc_id == result.doc_id).allowed_roles
        for result in plan.retrieval_results
    )


def test_baseline_scores_all_30_and_can_retrieve_guest_unauthorized_documents(
    bundle, security_resources, monkeypatch
) -> None:
    planner = _planner(bundle, security_resources)
    query = _run(_query("crafted cross-role query"))
    observed: list[tuple[str, ...]] = []

    def spy(index, vector, eligible):
        observed.append(eligible)
        return actual_retrieve(index, vector, eligible)

    monkeypatch.setattr("dataguard.rag.planner.retrieve", spy)
    plan = _plan(planner, query, question="crafted cross-role query")
    assert observed == [tuple(document.doc_id for document in bundle.corpus.documents)]
    assert len(observed[0]) == 30
    assert plan.authorization_denials == ()
    assert all(
        Role.GUEST
        not in next(doc for doc in bundle.corpus.documents if doc.doc_id == result.doc_id).allowed_roles
        for result in plan.retrieval_results
    )


def test_same_query_handle_plans_both_modes_without_second_embedding(bundle, security_resources) -> None:
    requests: list[httpx.Request] = []
    question = "paired synthetic query"
    query = _run(_query(question, observed=requests))
    planner = _planner(bundle, security_resources)
    baseline = _plan(planner, query, question=question, mode="baseline")
    guarded = _plan(planner, query, question=question, mode="guarded")
    assert len(requests) == 1
    assert baseline.mode is RagMode.BASELINE and guarded.mode is RagMode.GUARDED


def test_security_reviewer_modes_share_identical_selected_document_json(
    bundle, security_resources
) -> None:
    question = "paired reviewer query"
    query = _run(_query(question))
    planner = _planner(bundle, security_resources)
    baseline = _plan(
        planner,
        query,
        subject="security_reviewer-01",
        question=question,
        mode="baseline",
    )
    guarded = _plan(
        planner,
        query,
        subject="security_reviewer-01",
        question=question,
        mode="guarded",
    )
    by_id = {document.doc_id: document for document in bundle.corpus.documents}
    baseline_json = canonical_documents_json(
        tuple(by_id[result.doc_id] for result in baseline.retrieval_results)
    )
    guarded_json = canonical_documents_json(
        tuple(by_id[result.doc_id] for result in guarded.retrieval_results)
    )
    assert baseline_json == guarded_json
    assert baseline_json in baseline.messages[0].content
    assert guarded_json in guarded.messages[1].content


def test_shared_canonical_document_json_exact_fields_order_and_real_escaping(
    bundle, security_resources
) -> None:
    question = 'query "quote" \\ {brace} \u4e2d\u6587'
    query = _run(_query(question))
    planner = _planner(bundle, security_resources)
    baseline = _plan(planner, query, question=question, mode="baseline")
    guarded = _plan(planner, query, question=question, mode="guarded")
    by_id = {document.doc_id: document for document in bundle.corpus.documents}
    baseline_documents = tuple(by_id[result.doc_id] for result in baseline.retrieval_results)
    guarded_documents = tuple(by_id[result.doc_id] for result in guarded.retrieval_results)
    baseline_json = canonical_documents_json(baseline_documents)
    guarded_json = canonical_documents_json(guarded_documents)
    assert baseline_json in baseline.messages[0].content
    assert guarded_json in guarded.messages[1].content
    for rendered, selected in ((baseline_json, baseline_documents), (guarded_json, guarded_documents)):
        decoded = json.loads(rendered)
        assert [item["doc_id"] for item in decoded] == [document.doc_id for document in selected]
        assert all(set(item) == {"doc_id", "title", "classification", "content"} for item in decoded)
    assert question in baseline.messages[0].content
    assert question in guarded.messages[2].content


@pytest.mark.parametrize(
    "documents",
    [
        (),
        [],
        (object(), object(), object(), object()),
    ],
)
def test_canonical_documents_json_rejects_wrong_length_and_type(documents: Any) -> None:
    with pytest.raises(RagPlanningError) as captured:
        canonical_documents_json(documents)
    assert captured.value.code is RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH


def test_canonical_documents_json_rejects_duplicate_document_id(bundle) -> None:
    document = bundle.corpus.documents[0]
    with pytest.raises(RagPlanningError) as captured:
        canonical_documents_json((document, document, document, document))
    assert captured.value.code is RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("classification", RAW_SENTINEL),
        ("content", RAW_SENTINEL + ("x" * 1200)),
        ("doc_id", [RAW_SENTINEL]),
    ],
)
def test_canonical_documents_json_revalidates_constructed_documents_without_echo(
    bundle, field: str, value: Any
) -> None:
    valid = bundle.corpus.documents[:4]
    payload = valid[0].model_dump(mode="python")
    payload[field] = value
    malicious = type(valid[0]).model_construct(**payload)
    with pytest.raises(RagPlanningError) as captured:
        canonical_documents_json((malicious, *valid[1:]))
    assert captured.value.code is RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH
    _assert_safe_error(captured.value)


@pytest.mark.parametrize("doc_id", ["", "x" * 129, 1])
def test_authorization_denial_contract_id_bounds_are_strict_and_minimized(doc_id: Any) -> None:
    with pytest.raises(ValidationError) as captured:
        AuthorizationDenial(doc_id=doc_id, reason="role_not_allowed")
    rendered = str(captured.value) + repr(captured.value)
    assert "input_value" not in rendered
    if isinstance(doc_id, str) and len(doc_id) > 10:
        assert doc_id not in rendered


def test_authorization_denial_validation_does_not_echo_dynamic_sentinel() -> None:
    with pytest.raises(ValidationError) as captured:
        AuthorizationDenial(doc_id=RAW_SENTINEL * 20, reason="role_not_allowed")
    assert RAW_SENTINEL not in str(captured.value) + repr(captured.value)


def test_message_isolation_shapes_are_exact_and_plan_repr_has_no_content(
    bundle, security_resources
) -> None:
    question = RAW_SENTINEL + ' " \\ {x}'
    query = _run(_query(question))
    planner = _planner(bundle, security_resources)
    baseline = _plan(planner, query, question=question, mode="baseline")
    guarded = _plan(planner, query, question=question, mode="guarded")
    system_content = security_resources.system_prompt.value.content
    assert [(message.role) for message in baseline.messages] == ["user"]
    assert system_content in baseline.messages[0].content
    assert [message.role for message in guarded.messages] == ["system", "user", "user"]
    assert guarded.messages[0].content == system_content
    assert question not in guarded.messages[0].content
    assert all(
        document.content not in guarded.messages[0].content
        for document in bundle.corpus.documents
    )
    rendered = repr(guarded)
    assert RAW_SENTINEL not in rendered
    assert system_content not in rendered
    assert not hasattr(guarded, "model_dump")


def test_whitespace_question_is_preserved_in_both_message_modes(bundle, security_resources) -> None:
    question = " \t\u3000\n"
    query = _run(_query(question))
    planner = _planner(bundle, security_resources)
    baseline = _plan(planner, query, question=question, mode="baseline")
    guarded = _plan(planner, query, question=question, mode="guarded")
    assert baseline.messages[0].content.endswith(question)
    assert guarded.messages[2].content.endswith(question)


def test_context_budget_exact_boundary_multibyte_and_plan_rejects_without_truncation(
    bundle, security_resources
) -> None:
    overhead = context_message_bytes((OllamaMessage(role="user", content="x"),)) - 1
    passing_content = "x" * (8192 - 512 - overhead)
    passing = (OllamaMessage(role="user", content=passing_content),)
    failing = (OllamaMessage(role="user", content=passing_content + "x"),)
    assert context_message_bytes(passing) + 512 == 8192
    assert context_message_bytes(failing) + 512 == 8193
    assert context_message_bytes((OllamaMessage(role="user", content="\u4e2d"),)) == overhead + 3

    question = "\U0001f642" * 2000
    observed: list[httpx.Request] = []
    query = _run(_query(question, observed=observed))
    planner = _planner(bundle, security_resources)
    with pytest.raises(RagPlanningError) as captured:
        _plan(planner, query, question=question, mode="guarded")
    assert captured.value.code is RagPlanningErrorCode.CONTEXT_BUDGET_EXCEEDED
    assert json.loads(observed[0].content)["input"] == [question]


@pytest.mark.parametrize(
    "payload",
    [
        {"role": "user"},
        {"role": "assistant", "content": RAW_SENTINEL},
        {"role": "user", "content": RAW_SENTINEL + ("x" * 32768)},
        {"role": "user", "content": {"value": RAW_SENTINEL}},
    ],
)
def test_context_budget_revalidates_unchecked_message_without_echo(
    payload: dict[str, Any],
) -> None:
    malformed = OllamaMessage.model_construct(**payload)
    with pytest.raises(RagPlanningError) as captured:
        context_message_bytes((malformed,))
    assert captured.value.code is RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH
    _assert_safe_error(captured.value)


def test_planner_factory_rejects_fixture_index_and_resource_binding_drift(
    bundle, security_resources
) -> None:
    index = _index(bundle.corpus, bundle.corpus_sha256)
    duplicate_identities = bundle.identities.model_copy(
        update={"identities": (bundle.identities.identities[0],) * 6}
    )
    bad_digest_resources = replace(
        security_resources,
        system_prompt=replace(security_resources.system_prompt, sha256="bad"),
    )
    cases = [
        (duplicate_identities, bundle.corpus, bundle.corpus_sha256, security_resources, index),
        (bundle.identities, bundle.corpus, "d" * 64, security_resources, index),
        (bundle.identities, bundle.corpus, bundle.corpus_sha256, bad_digest_resources, index),
    ]
    for args in cases:
        with pytest.raises(RagPlanningError) as captured:
            create_rag_planner(*args)
        assert captured.value.code is RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH
        _assert_safe_error(captured.value)

    reversed_corpus = bundle.corpus.model_copy(
        update={"documents": tuple(reversed(bundle.corpus.documents))}
    )
    reversed_index = _index(reversed_corpus, bundle.corpus_sha256)
    with pytest.raises(RagPlanningError) as captured:
        create_rag_planner(
            bundle.identities,
            bundle.corpus,
            bundle.corpus_sha256,
            security_resources,
            reversed_index,
        )
    assert captured.value.code is RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH


def test_planner_factory_revalidates_forged_resource_dataclasses_without_echo(
    bundle, security_resources
) -> None:
    index = _index(bundle.corpus, bundle.corpus_sha256)
    system_artifact = security_resources.system_prompt
    system_payload = system_artifact.value.model_dump(mode="python")
    system_payload["content"] = RAW_SENTINEL
    unchecked_system = type(system_artifact.value).model_construct(**system_payload)

    baseline_artifact = security_resources.baseline_prompt
    system_marker = system_artifact.value.system_canary_literal
    cross_resource_baseline = baseline_artifact.value.model_copy(
        update={"template": system_marker + "\n" + baseline_artifact.value.template}
    )
    cases = (
        replace(security_resources, system_prompt=object()),
        replace(
            security_resources,
            system_prompt=ResourceArtifact(
                value=unchecked_system,
                sha256=system_artifact.sha256,
            ),
        ),
        replace(
            security_resources,
            baseline_prompt=ResourceArtifact(
                value=cross_resource_baseline,
                sha256=baseline_artifact.sha256,
            ),
        ),
    )
    for resources in cases:
        with pytest.raises(RagPlanningError) as captured:
            create_rag_planner(
                bundle.identities,
                bundle.corpus,
                bundle.corpus_sha256,
                resources,
                index,
            )
        assert captured.value.code is RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH
        _assert_safe_error(captured.value)
        assert system_marker not in str(captured.value) + repr(captured.value.as_dict())


@pytest.mark.parametrize(
    ("digest", "dimensions"),
    [("d" * 64, DIMENSIONS), (EMBEDDING_DIGEST, 2)],
)
def test_plan_rejects_query_model_digest_and_dimension_drift(
    bundle, security_resources, digest: str, dimensions: int
) -> None:
    planner = _planner(bundle, security_resources)
    query = _run(_query("synthetic", health=_health(digest=digest, dimensions=dimensions)))
    with pytest.raises(RagPlanningError) as captured:
        _plan(planner, query, question="synthetic")
    assert captured.value.code is RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH


def test_retrieval_missing_duplicate_and_short_results_are_manifest_mismatch(
    bundle, security_resources, monkeypatch
) -> None:
    planner = _planner(bundle, security_resources)
    query = _run(_query("synthetic"))
    valid = actual_retrieve(
        planner._index,  # noqa: SLF001 - intentional malformed dependency injection
        (1.0, 0.0, 0.0),
        tuple(document.doc_id for document in bundle.corpus.documents),
    )
    malformed = [
        valid[:3],
        (valid[0], valid[0], valid[2], valid[3]),
        (
            RetrievalResult(doc_id="unknown-document", similarity_score=1.0),
            *valid[1:],
        ),
    ]
    for results in malformed:
        monkeypatch.setattr("dataguard.rag.planner.retrieve", lambda *args, value=results: value)
        with pytest.raises(RagPlanningError) as captured:
            _plan(planner, query, question="synthetic")
        assert captured.value.code is RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH


def test_planner_import_has_no_file_network_database_or_resource_io() -> None:
    script = r'''
import builtins
import pathlib
import socket
import httpx
import pydantic
import dataguard.domain
import dataguard.ollama
import dataguard.resources
import dataguard.vector_index

def forbidden(*args, **kwargs):
    raise RuntimeError("unexpected I/O")

builtins.open = forbidden
pathlib.Path.open = forbidden
pathlib.Path.read_bytes = forbidden
socket.socket = forbidden
httpx.AsyncClient = forbidden
import dataguard.rag
'''
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_plan_never_calls_chat_detector_or_vector_index_store(
    bundle, security_resources, monkeypatch
) -> None:
    query = _run(_query("planning only"))
    planner = _planner(bundle, security_resources)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("out-of-scope runtime component called")

    monkeypatch.setattr(OllamaClient, "chat", forbidden)
    monkeypatch.setattr(WholeOutputDetector, "evaluate", forbidden)
    monkeypatch.setattr(VectorIndexStore, "prepare", forbidden)
    monkeypatch.setattr(VectorIndexStore, "read", forbidden)
    monkeypatch.setattr(VectorIndexStore, "load_validated", forbidden)
    monkeypatch.setattr(VectorIndexStore, "write", forbidden)

    plan = _plan(planner, query, question="planning only", mode="guarded")
    assert plan.mode is RagMode.GUARDED
    assert len(plan.retrieval_results) == 4


def test_errors_never_echo_dynamic_request_or_marker(bundle, security_resources) -> None:
    planner = _planner(bundle, security_resources)
    query = _run(_query("safe"))
    with pytest.raises(RagPlanningError) as captured:
        _run(
            planner.plan(
                corpus_version="invalid version " + RAW_SENTINEL,
                subject_id=RAW_SENTINEL,
                question=RAW_SENTINEL,
                mode=RAW_SENTINEL,
                query_embedding=query,
            )
        )
    _assert_safe_error(captured.value)
