from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import httpx
import pytest

from dataguard.config import RuntimeSettings
from dataguard.detector import (
    DetectionAction,
    DetectionEvidence,
    DetectionType,
    DetectorMode,
    DetectorOutcome,
    DetectorResult,
    WholeOutputDetector,
    build_whole_output_detector,
)
from dataguard.domain import Classification, Role
from dataguard.ollama import OllamaAdapterError, OllamaClient, OllamaErrorCode, OllamaMessage
from dataguard.ollama import OllamaHealthFacts, OllamaModelFacts
from dataguard.ollama.client import EMBEDDING_MODEL, GENERATION_MODEL
from dataguard.rag import (
    AuthorizationDenial,
    RagExecutionError,
    RagExecutionErrorCode,
    RagExecutionResult,
    RagExecutor,
    RagMode,
    context_message_bytes,
    create_rag_executor,
    create_rag_planner,
    embed_query,
)
from dataguard.rag.models import _create_rag_plan
from dataguard.resources import FIXED_BLOCKED_REPLY, load_security_resources
from dataguard.validation import load_fixture_bundle
from dataguard.vector_index import (
    RetrievalResult,
    build_vector_index,
    validate_vector_index_binding,
)
from dataguard.vector_index.store import VectorIndexStore


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_SENTINEL = "A4B_RAW_OUTPUT_SENTINEL_SHOULD_NOT_APPEAR"


def _run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


@pytest.fixture(scope="module")
def accepted():
    loaded = load_fixture_bundle(PROJECT_ROOT)
    assert loaded.ok and loaded.bundle is not None
    resources = load_security_resources()
    detector = build_whole_output_detector(resources, loaded.bundle.corpus)
    return loaded.bundle, resources, detector


def _plan(
    mode: RagMode,
    *,
    role: Role = Role.GUEST,
    messages: tuple[OllamaMessage, ...] | None = None,
):
    if messages is None:
        messages = (
            (OllamaMessage(role="user", content="synthetic baseline payload"),)
            if mode is RagMode.BASELINE
            else (
                OllamaMessage(role="system", content="synthetic system prompt"),
                OllamaMessage(role="user", content='[{"synthetic":"document"}]'),
                OllamaMessage(role="user", content="synthetic query"),
            )
        )
    denial_count = (
        0
        if mode is RagMode.BASELINE
        else {Role.GUEST: 20, Role.EMPLOYEE: 10, Role.SECURITY_REVIEWER: 0}[role]
    )
    return _create_rag_plan(
        mode=mode,
        resolved_role=role,
        retrieval_results=tuple(
            RetrievalResult(doc_id=f"selected-{index}", similarity_score=1.0 - index / 10)
            for index in range(4)
        ),
        authorization_denials=tuple(
            AuthorizationDenial(doc_id=f"denied-{index}", reason="role_not_allowed")
            for index in range(denial_count)
        ),
        messages=messages,
        context_message_bytes=context_message_bytes(messages),
    )


def _chat_response(raw_output: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": GENERATION_MODEL,
            "message": {"role": "assistant", "content": raw_output},
            "done": True,
        },
        headers={"Content-Type": "application/json"},
    )


async def _execute(
    plan,
    detector: WholeOutputDetector,
    raw_output: str,
    *,
    requests: list[httpx.Request] | None = None,
) -> RagExecutionResult:
    async def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        return _chat_response(raw_output)

    async with OllamaClient(
        RuntimeSettings(), transport=httpx.MockTransport(handler)
    ) as client:
        return await create_rag_executor(client, detector).execute(plan)


def _detection(result: RagExecutionResult, evidence_id: str) -> DetectionEvidence:
    return next(item for item in result.detections if item.evidence_id == evidence_id)


def _assert_internal_error(error: RagExecutionError) -> None:
    rendered = str(error) + repr(error) + repr(error.as_dict())
    assert error.code is RagExecutionErrorCode.INTERNAL_ERROR
    assert error.as_dict()["code"] == "internal_error"
    assert set(error.as_dict()) == {"code", "message"}
    assert RAW_SENTINEL not in rendered
    assert "DG_" not in rendered
    assert "http://" not in rendered


def _fullwidth_ascii(value: str) -> str:
    return "".join(
        chr(ord(character) + 0xFEE0)
        if 0x21 <= ord(character) <= 0x7E
        else character
        for character in value
    )


def test_chat_and_detector_each_receive_exact_input_once(accepted, monkeypatch) -> None:
    _, _, detector = accepted
    plan = _plan(RagMode.GUARDED, role=Role.SECURITY_REVIEWER)
    raw = "exact complete synthetic model output"
    requests: list[httpx.Request] = []
    detector_calls: list[tuple[str, Role, DetectorMode]] = []
    original = WholeOutputDetector.evaluate

    def spy(self, raw_output: str, *, role: Role, mode: DetectorMode):
        detector_calls.append((raw_output, role, mode))
        return original(self, raw_output, role=role, mode=mode)

    monkeypatch.setattr(WholeOutputDetector, "evaluate", spy)
    result = _run(_execute(plan, detector, raw, requests=requests))

    assert result.reply == raw and result.outcome is DetectorOutcome.ANSWERED
    assert len(requests) == 1
    request_body = json.loads(requests[0].content)
    assert request_body["messages"] == [
        message.model_dump(mode="json") for message in plan.messages
    ]
    assert detector_calls == [(raw, Role.SECURITY_REVIEWER, DetectorMode.GUARDED)]


def test_baseline_three_detection_types_are_observed_and_raw_is_returned(accepted) -> None:
    bundle, resources, detector = accepted
    document_canary = bundle.corpus.documents[0].canaries[0]
    confidential = next(
        document
        for document in bundle.corpus.documents
        if document.classification is Classification.CONFIDENTIAL
    )
    fragment = confidential.protected_fragments[0]
    cases = (
        (document_canary.value, document_canary.canary_id),
        (
            resources.system_prompt.value.system_canary_literal,
            str(resources.system_prompt.value.system_canary_evidence_id),
        ),
        (fragment.value, fragment.fragment_id),
    )
    for marker, evidence_id in cases:
        raw = RAW_SENTINEL + " " + marker
        result = _run(_execute(_plan(RagMode.BASELINE), detector, raw))
        evidence = _detection(result, evidence_id)
        assert result.outcome is DetectorOutcome.ANSWERED
        assert result.reply == raw
        assert evidence.action is DetectionAction.OBSERVED


def test_guarded_canaries_and_unauthorized_fragment_block_without_raw_retention(accepted) -> None:
    bundle, resources, detector = accepted
    document_canary = bundle.corpus.documents[0].canaries[0]
    confidential = next(
        document
        for document in bundle.corpus.documents
        if document.classification is Classification.CONFIDENTIAL
    )
    fragment = confidential.protected_fragments[0]
    cases = (
        (document_canary.value, document_canary.canary_id),
        (
            resources.system_prompt.value.system_canary_literal,
            str(resources.system_prompt.value.system_canary_evidence_id),
        ),
        (fragment.value, fragment.fragment_id),
    )
    for marker, evidence_id in cases:
        raw = RAW_SENTINEL + " " + marker
        result = _run(_execute(_plan(RagMode.GUARDED), detector, raw))
        evidence = _detection(result, evidence_id)
        assert result.outcome is DetectorOutcome.BLOCKED
        assert result.reply == FIXED_BLOCKED_REPLY
        assert evidence.violation is True
        assert evidence.action is DetectionAction.BLOCKED
        assert RAW_SENTINEL not in repr(result)
        assert marker not in repr(result)
        assert not hasattr(result, "model_dump")


def test_guarded_authorized_fragment_is_observed_without_block(accepted) -> None:
    bundle, _, detector = accepted
    confidential = next(
        document
        for document in bundle.corpus.documents
        if document.classification is Classification.CONFIDENTIAL
    )
    fragment = confidential.protected_fragments[0]
    raw = RAW_SENTINEL + " " + fragment.value
    result = _run(
        _execute(
            _plan(RagMode.GUARDED, role=Role.SECURITY_REVIEWER),
            detector,
            raw,
        )
    )
    evidence = _detection(result, fragment.fragment_id)
    assert result.outcome is DetectorOutcome.ANSWERED
    assert result.reply == raw
    assert evidence.violation is False
    assert evidence.action is DetectionAction.OBSERVED


@pytest.mark.parametrize("mode", [RagMode.BASELINE, RagMode.GUARDED])
def test_empty_model_output_is_returned_unmodified(accepted, mode: RagMode) -> None:
    _, _, detector = accepted
    result = _run(_execute(_plan(mode), detector, ""))
    assert result.reply == ""
    assert result.outcome is DetectorOutcome.ANSWERED
    assert result.detections == ()


def test_unicode_and_zero_width_raw_is_not_normalized_before_detector_or_return(accepted) -> None:
    bundle, _, detector = accepted
    canary = bundle.corpus.documents[0].canaries[0]
    fullwidth = _fullwidth_ascii(canary.value)
    raw = "\u200b".join(fullwidth) + "\u2060"
    result = _run(_execute(_plan(RagMode.BASELINE), detector, raw))
    assert result.reply == raw
    assert _detection(result, canary.canary_id).action is DetectionAction.OBSERVED


def test_chat_error_propagates_unchanged_and_detector_is_not_called(accepted, monkeypatch) -> None:
    _, _, detector = accepted
    detector_calls = 0

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        nonlocal detector_calls
        detector_calls += 1
        raise AssertionError("detector must not run")

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(RAW_SENTINEL, request=request)

    monkeypatch.setattr(WholeOutputDetector, "evaluate", forbidden)

    async def exercise() -> None:
        async with OllamaClient(
            RuntimeSettings(), transport=httpx.MockTransport(handler)
        ) as client:
            await create_rag_executor(client, detector).execute(_plan(RagMode.BASELINE))

    with pytest.raises(OllamaAdapterError) as captured:
        _run(exercise())
    assert captured.value.code is OllamaErrorCode.MODEL_TIMEOUT
    assert detector_calls == 0
    assert RAW_SENTINEL not in str(captured.value) + repr(captured.value.as_dict())


def test_chat_cancellation_propagates_and_detector_is_not_called(accepted, monkeypatch) -> None:
    _, _, detector = accepted
    detector_calls = 0

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        nonlocal detector_calls
        detector_calls += 1
        raise AssertionError("detector must not run")

    async def handler(request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    monkeypatch.setattr(WholeOutputDetector, "evaluate", forbidden)

    async def exercise() -> None:
        async with OllamaClient(
            RuntimeSettings(), transport=httpx.MockTransport(handler)
        ) as client:
            await create_rag_executor(client, detector).execute(_plan(RagMode.BASELINE))

    with pytest.raises(asyncio.CancelledError):
        _run(exercise())
    assert detector_calls == 0


def test_malformed_detector_results_are_internal_errors_without_echo(accepted, monkeypatch) -> None:
    _, _, detector = accepted
    malformed_results: tuple[object, ...] = (
        object(),
        DetectorResult.model_construct(
            reply=RAW_SENTINEL,
            outcome="invalid-outcome",
            detections=(),
        ),
        DetectorResult(
            reply="not-the-raw-output",
            outcome=DetectorOutcome.ANSWERED,
            detections=(),
        ),
        DetectorResult(
            reply=RAW_SENTINEL,
            outcome=DetectorOutcome.ANSWERED,
            detections=(
                DetectionEvidence(
                    type=DetectionType.UNAUTHORIZED_PROTECTED_FRAGMENT,
                    evidence_id="opaque-evidence",
                    violation=True,
                    action=DetectionAction.OBSERVED,
                ),
            ),
        ),
    )
    plans = (
        _plan(RagMode.BASELINE),
        _plan(RagMode.BASELINE),
        _plan(RagMode.BASELINE),
        _plan(RagMode.GUARDED),
    )
    for malformed, plan in zip(malformed_results, plans, strict=True):
        monkeypatch.setattr(
            WholeOutputDetector,
            "evaluate",
            lambda *args, value=malformed, **kwargs: value,
        )
        with pytest.raises(RagExecutionError) as captured:
            _run(_execute(plan, detector, RAW_SENTINEL))
        _assert_internal_error(captured.value)


def test_detector_exception_is_minimized_internal_error(accepted, monkeypatch) -> None:
    _, _, detector = accepted

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(RAW_SENTINEL)

    monkeypatch.setattr(WholeOutputDetector, "evaluate", broken)
    with pytest.raises(RagExecutionError) as captured:
        _run(_execute(_plan(RagMode.BASELINE), detector, RAW_SENTINEL))
    _assert_internal_error(captured.value)


def test_forged_plan_and_mode_drift_fail_before_chat_or_detector(accepted) -> None:
    _, _, detector = accepted
    for field, value in (
        ("mode", "baseline"),
        ("resolved_role", "guest"),
        ("context_message_bytes", 1),
        (
            "messages",
            (OllamaMessage.model_construct(role="assistant", content=RAW_SENTINEL),),
        ),
    ):
        plan = _plan(RagMode.BASELINE)
        object.__setattr__(plan, field, value)
        calls = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return _chat_response(RAW_SENTINEL)

        async def exercise() -> None:
            async with OllamaClient(
                RuntimeSettings(), transport=httpx.MockTransport(handler)
            ) as client:
                await create_rag_executor(client, detector).execute(plan)

        with pytest.raises(RagExecutionError) as captured:
            _run(exercise())
        _assert_internal_error(captured.value)
        assert calls == 0


def test_execution_never_embeds_retrieves_or_touches_index_store(accepted, monkeypatch) -> None:
    _, _, detector = accepted
    import dataguard.rag.planner as planner_module

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("out-of-scope component called")

    monkeypatch.setattr(OllamaClient, "embed", forbidden)
    monkeypatch.setattr(planner_module, "retrieve", forbidden)
    monkeypatch.setattr(VectorIndexStore, "prepare", forbidden)
    monkeypatch.setattr(VectorIndexStore, "read", forbidden)
    monkeypatch.setattr(VectorIndexStore, "load_validated", forbidden)
    monkeypatch.setattr(VectorIndexStore, "write", forbidden)
    result = _run(_execute(_plan(RagMode.BASELINE), detector, "safe output"))
    assert result.reply == "safe output"


def test_factory_result_and_executor_are_controlled_frozen_and_content_safe(accepted) -> None:
    _, _, detector = accepted
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _chat_response("unused")

    async def exercise() -> None:
        async with OllamaClient(
            RuntimeSettings(), transport=httpx.MockTransport(handler)
        ) as client:
            executor = create_rag_executor(client, detector)
            assert calls == 0
            assert RAW_SENTINEL not in repr(executor)
            with pytest.raises(FrozenInstanceError):
                executor._detector = object()  # type: ignore[misc]
            with pytest.raises(RagExecutionError):
                RagExecutor(client, detector, _token=object())
            with pytest.raises(RagExecutionError) as invalid_client:
                create_rag_executor(object(), detector)  # type: ignore[arg-type]
            _assert_internal_error(invalid_client.value)
            malformed_detector = object.__new__(WholeOutputDetector)
            with pytest.raises(RagExecutionError) as invalid_detector:
                create_rag_executor(client, malformed_detector)
            _assert_internal_error(invalid_detector.value)

    _run(exercise())
    with pytest.raises(RagExecutionError):
        RagExecutionResult(
            reply=RAW_SENTINEL,
            outcome=DetectorOutcome.ANSWERED,
            detections=(),
            _token=object(),
        )
    result = _run(_execute(_plan(RagMode.BASELINE), detector, RAW_SENTINEL))
    with pytest.raises(FrozenInstanceError):
        result.reply = "changed"  # type: ignore[misc]
    assert RAW_SENTINEL not in repr(result)


def test_real_a4a_paired_plans_execute_without_second_embed_or_retrieve(
    accepted, monkeypatch
) -> None:
    bundle, resources, detector = accepted
    requests: list[httpx.Request] = []
    retrieval_calls = 0
    import dataguard.rag.planner as planner_module

    actual_retrieve = planner_module.retrieve

    def retrieve_spy(*args: Any, **kwargs: Any):
        nonlocal retrieval_calls
        retrieval_calls += 1
        return actual_retrieve(*args, **kwargs)

    monkeypatch.setattr(planner_module, "retrieve", retrieve_spy)

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/embed":
            inputs = json.loads(request.content)["input"]
            return httpx.Response(
                200,
                json={
                    "model": EMBEDDING_MODEL,
                    "embeddings": [[1.0, 0.1, 0.01] for _ in inputs],
                },
                headers={"Content-Type": "application/json"},
            )
        if request.url.path == "/api/chat":
            return _chat_response("safe synthetic paired answer")
        raise AssertionError("unexpected local endpoint")

    health = OllamaHealthFacts(
        version="0.12.1",
        generation_model=OllamaModelFacts(
            tag=GENERATION_MODEL,
            digest="a" * 64,
        ),
        embedding_model=OllamaModelFacts(
            tag=EMBEDDING_MODEL,
            digest="b" * 64,
        ),
        embedding_dimensions=3,
    )

    async def exercise() -> tuple[RagExecutionResult, RagExecutionResult]:
        async with OllamaClient(
            RuntimeSettings(), transport=httpx.MockTransport(handler)
        ) as client:
            artifact = await build_vector_index(
                bundle.corpus,
                bundle.corpus_sha256,
                health,
                client,
            )
            index = validate_vector_index_binding(
                artifact,
                bundle.corpus,
                bundle.corpus_sha256,
                health,
            )
            planner = create_rag_planner(
                bundle.identities,
                bundle.corpus,
                bundle.corpus_sha256,
                resources,
                index,
            )
            question = "paired synthetic execution question"
            query = await embed_query(question, health, client)
            baseline = await planner.plan(
                corpus_version="synthetic-v1",
                subject_id="security_reviewer-01",
                question=question,
                mode="baseline",
                query_embedding=query,
            )
            guarded = await planner.plan(
                corpus_version="synthetic-v1",
                subject_id="security_reviewer-01",
                question=question,
                mode="guarded",
                query_embedding=query,
            )
            before_execution = (
                sum(request.url.path == "/api/embed" for request in requests),
                retrieval_calls,
            )
            executor = create_rag_executor(client, detector)
            results = await executor.execute(baseline), await executor.execute(guarded)
            after_execution = (
                sum(request.url.path == "/api/embed" for request in requests),
                retrieval_calls,
            )
            assert before_execution == (2, 2)
            assert after_execution == before_execution
            return results

    baseline_result, guarded_result = _run(exercise())
    assert baseline_result.reply == guarded_result.reply == "safe synthetic paired answer"
    assert baseline_result.outcome is guarded_result.outcome is DetectorOutcome.ANSWERED
    assert sum(request.url.path == "/api/chat" for request in requests) == 2


def test_detector_result_repr_hides_answered_raw_output(accepted) -> None:
    _, _, detector = accepted
    intermediate = detector.evaluate(
        RAW_SENTINEL,
        role=Role.GUEST,
        mode=DetectorMode.BASELINE,
    )
    assert RAW_SENTINEL not in repr(intermediate)
    assert intermediate.model_dump()["reply"] == RAW_SENTINEL


def test_execution_import_performs_no_file_network_database_or_resource_io() -> None:
    script = r'''
import builtins
import pathlib
import socket
import httpx
import pydantic
import dataguard.domain
import dataguard.ollama
import dataguard.resources
import dataguard.detector
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
