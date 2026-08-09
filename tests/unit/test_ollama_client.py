from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from dataguard.config import RuntimeSettings
from dataguard.ollama import (
    OllamaAdapterError,
    OllamaClient,
    OllamaErrorCode,
    OllamaHealthFacts,
    OllamaMessage,
    OllamaModelFacts,
)
from dataguard.ollama.client import EMBEDDING_MODEL, GENERATION_MODEL


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_SENTINEL = "RAW_REMOTE_MARKER_SHOULD_NOT_APPEAR"
DIGEST_A = "a" * 64
DIGEST_B = "sha256:" + "b" * 64


def _run(awaitable: Awaitable[Any]) -> Any:
    return asyncio.run(awaitable)


def _json_response(payload: Any, *, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload, headers={"Content-Type": "application/json"})


def _probe_handler(requests: list[httpx.Request]) -> Callable[[httpx.Request], Awaitable[httpx.Response]]:
    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/version":
            return _json_response({"version": "0.12.1"})
        if request.url.path == "/api/tags":
            return _json_response(
                {
                    "models": [
                        {
                            "name": GENERATION_MODEL,
                            "model": GENERATION_MODEL,
                            "digest": DIGEST_A,
                            "size": 1,
                            "details": {},
                        },
                        {
                            "name": EMBEDDING_MODEL,
                            "model": EMBEDDING_MODEL,
                            "digest": DIGEST_B,
                            "modified_at": "2026-08-09T00:00:00Z",
                        },
                    ]
                }
            )
        if request.url.path == "/api/show":
            return _json_response(
                {
                    "model_info": {
                        "general.architecture": "synthetic",
                        "qwen3.embedding_length": 1024,
                    },
                    "template": RAW_SENTINEL,
                    "license": "synthetic test metadata",
                    "parameters": "synthetic",
                    "details": {},
                    "capabilities": ["embedding"],
                }
            )
        raise AssertionError("unexpected request")

    return handler


async def _probe_with_handler(
    handler: Callable[[httpx.Request], Awaitable[httpx.Response]],
    *,
    settings: RuntimeSettings | None = None,
) -> OllamaHealthFacts:
    async with OllamaClient(
        settings or RuntimeSettings(),
        transport=httpx.MockTransport(handler),
    ) as client:
        return await client.probe()


async def _embed_with_handler(
    handler: Callable[[httpx.Request], Awaitable[httpx.Response]],
    *,
    inputs: tuple[str, ...] = ("synthetic input",),
    expected_dimensions: int | None = None,
    settings: RuntimeSettings | None = None,
) -> tuple[tuple[float, ...], ...]:
    async with OllamaClient(
        settings or RuntimeSettings(),
        transport=httpx.MockTransport(handler),
    ) as client:
        return await client.embed(inputs, expected_dimensions=expected_dimensions)


async def _chat_with_handler(
    handler: Callable[[httpx.Request], Awaitable[httpx.Response]],
    *,
    messages: tuple[OllamaMessage, ...] = (OllamaMessage(role="user", content="hello"),),
    settings: RuntimeSettings | None = None,
) -> str:
    async with OllamaClient(
        settings or RuntimeSettings(),
        transport=httpx.MockTransport(handler),
    ) as client:
        return await client.chat(messages)


def _assert_error(error: OllamaAdapterError, code: OllamaErrorCode) -> None:
    rendered = " ".join((str(error), repr(error), repr(error.as_dict())))
    assert error.code is code
    assert error.as_dict()["code"] == code.value
    assert set(error.as_dict()) == {"code", "message"}
    assert RAW_SENTINEL not in rendered
    assert "http://" not in rendered


def test_probe_uses_exact_local_requests_and_returns_minimized_frozen_facts() -> None:
    requests: list[httpx.Request] = []
    facts = _run(_probe_with_handler(_probe_handler(requests)))

    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/api/version"),
        ("GET", "/api/tags"),
        ("POST", "/api/show"),
    ]
    assert all(request.url.host == "127.0.0.1" for request in requests)
    assert all(request.headers["accept"] == "application/json" for request in requests)
    assert all("authorization" not in request.headers for request in requests)
    assert "content-type" not in requests[0].headers
    assert "content-type" not in requests[1].headers
    assert requests[2].headers["content-type"] == "application/json"
    assert json.loads(requests[2].content) == {"model": EMBEDDING_MODEL, "verbose": False}
    assert facts.model_dump() == {
        "version": "0.12.1",
        "generation_model": {"tag": GENERATION_MODEL, "digest": DIGEST_A},
        "embedding_model": {"tag": EMBEDDING_MODEL, "digest": DIGEST_B},
        "embedding_dimensions": 1024,
    }
    assert RAW_SENTINEL not in facts.model_dump_json()
    with pytest.raises(ValidationError):
        OllamaHealthFacts.model_validate({**facts.model_dump(), "unknown": True})
    with pytest.raises(ValidationError):
        facts.version = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("digest", [DIGEST_A, DIGEST_B])
def test_model_facts_direct_construction_accepts_only_contract_digests(digest: str) -> None:
    facts = OllamaModelFacts(tag=GENERATION_MODEL, digest=digest)
    assert facts.digest == digest


@pytest.mark.parametrize(
    "digest",
    [
        RAW_SENTINEL,
        "A" * 64,
        "sha512:" + "a" * 64,
        "a" * 63,
        "a" * 65,
    ],
)
def test_model_facts_direct_construction_rejects_digest_drift_without_echo(
    digest: str,
) -> None:
    with pytest.raises(ValidationError) as captured:
        OllamaModelFacts(tag=GENERATION_MODEL, digest=digest)
    assert digest not in str(captured.value)
    assert RAW_SENTINEL not in repr(captured.value)


@pytest.mark.parametrize(
    ("generation_tag", "embedding_tag"),
    [
        (EMBEDDING_MODEL, GENERATION_MODEL),
        (GENERATION_MODEL, GENERATION_MODEL),
        (EMBEDDING_MODEL, EMBEDDING_MODEL),
        (RAW_SENTINEL, EMBEDDING_MODEL),
        (GENERATION_MODEL, RAW_SENTINEL),
    ],
)
def test_health_facts_direct_construction_requires_locked_distinct_tags_without_echo(
    generation_tag: str,
    embedding_tag: str,
) -> None:
    with pytest.raises(ValidationError) as captured:
        OllamaHealthFacts(
            version="0.12.1",
            generation_model=OllamaModelFacts(tag=generation_tag, digest=DIGEST_A),
            embedding_model=OllamaModelFacts(tag=embedding_tag, digest=DIGEST_A),
            embedding_dimensions=1024,
        )
    rendered = str(captured.value) + repr(captured.value)
    assert RAW_SENTINEL not in rendered


def test_embed_request_shape_and_immutable_finite_response() -> None:
    observed: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return _json_response(
            {
                "model": EMBEDDING_MODEL,
                "embeddings": [[1, 2.5], [3.0, 4]],
                "total_duration": 1,
                "load_duration": 0,
                "prompt_eval_count": 2,
            }
        )

    result = _run(
        _embed_with_handler(
            handler,
            inputs=("first", "second"),
            expected_dimensions=2,
        )
    )

    assert result == ((1.0, 2.5), (3.0, 4.0))
    assert len(observed) == 1
    request = observed[0]
    assert (request.method, request.url.path) == ("POST", "/api/embed")
    assert request.headers["accept"] == "application/json"
    assert request.headers["content-type"] == "application/json"
    assert json.loads(request.content) == {
        "model": EMBEDDING_MODEL,
        "input": ["first", "second"],
        "truncate": False,
    }


def test_chat_request_shape_has_locked_options_no_tools_and_accepts_empty_content() -> None:
    observed: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return _json_response(
            {
                "model": GENERATION_MODEL,
                "message": {"role": "assistant", "content": "", "thinking": ""},
                "done": True,
                "done_reason": "stop",
                "eval_count": 0,
            }
        )

    messages = (
        OllamaMessage(role="system", content="synthetic system"),
        OllamaMessage(role="user", content="synthetic question"),
    )
    assert _run(_chat_with_handler(handler, messages=messages)) == ""

    request = observed[0]
    assert (request.method, request.url.path) == ("POST", "/api/chat")
    body = json.loads(request.content)
    assert body == {
        "model": GENERATION_MODEL,
        "messages": [
            {"role": "system", "content": "synthetic system"},
            {"role": "user", "content": "synthetic question"},
        ],
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0,
            "seed": 42,
            "top_k": 20,
            "top_p": 0.9,
            "num_ctx": 8192,
            "num_predict": 512,
        },
    }
    assert "tools" not in body


def test_construct_import_factory_and_context_lifecycle_are_side_effect_free() -> None:
    calls = 0
    factory_kwargs: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response({"unused": True})

    transport = httpx.MockTransport(handler)

    def factory(**kwargs: Any) -> httpx.AsyncClient:
        factory_kwargs.update(kwargs)
        return httpx.AsyncClient(**kwargs)

    async def exercise() -> None:
        client = OllamaClient(RuntimeSettings(), transport=transport, client_factory=factory)
        assert calls == 0
        assert factory_kwargs["base_url"] == "http://127.0.0.1:11434"
        await client.aclose()
        assert client._client.is_closed  # noqa: SLF001 - explicit lifecycle assertion

    _run(exercise())
    assert calls == 0

    script = """
import httpx

def forbidden(*args, **kwargs):
    raise RuntimeError("network construction attempted")

httpx.AsyncClient = forbidden
import dataguard.ollama.client
"""
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


@pytest.mark.parametrize(
    ("operation", "raised", "expected"),
    [
        ("probe", httpx.ConnectError(RAW_SENTINEL), OllamaErrorCode.OLLAMA_UNAVAILABLE),
        ("embed", httpx.ConnectError(RAW_SENTINEL), OllamaErrorCode.OLLAMA_UNAVAILABLE),
        ("chat", httpx.ConnectError(RAW_SENTINEL), OllamaErrorCode.OLLAMA_UNAVAILABLE),
        ("probe", httpx.ReadTimeout(RAW_SENTINEL), OllamaErrorCode.OLLAMA_UNAVAILABLE),
        ("embed", httpx.ReadTimeout(RAW_SENTINEL), OllamaErrorCode.MODEL_TIMEOUT),
        ("chat", httpx.ReadTimeout(RAW_SENTINEL), OllamaErrorCode.MODEL_TIMEOUT),
    ],
)
def test_connect_and_timeout_mapping_is_operation_specific_and_minimized(
    operation: str,
    raised: Exception,
    expected: OllamaErrorCode,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise raised

    with pytest.raises(OllamaAdapterError) as captured:
        if operation == "probe":
            _run(_probe_with_handler(handler))
        elif operation == "embed":
            _run(_embed_with_handler(handler))
        else:
            _run(_chat_with_handler(handler))
    _assert_error(captured.value, expected)


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ("embed", OllamaErrorCode.EMBEDDING_MODEL_UNAVAILABLE),
        ("chat", OllamaErrorCode.GENERATION_MODEL_UNAVAILABLE),
    ],
)
def test_model_request_404_maps_without_reading_body(operation: str, expected: OllamaErrorCode) -> None:
    body_read = False

    class ForbiddenBody(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            nonlocal body_read
            body_read = True
            raise AssertionError(RAW_SENTINEL)
            yield b""  # pragma: no cover

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, stream=ForbiddenBody())

    with pytest.raises(OllamaAdapterError) as captured:
        if operation == "embed":
            _run(_embed_with_handler(handler))
        else:
            _run(_chat_with_handler(handler))
    _assert_error(captured.value, expected)
    assert body_read is False


@pytest.mark.parametrize("status", [400, 500, 503])
def test_other_http_status_is_protocol_error_and_error_body_is_never_read(status: int) -> None:
    body_read = False

    class ForbiddenBody(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            nonlocal body_read
            body_read = True
            raise AssertionError(RAW_SENTINEL)
            yield b""  # pragma: no cover

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, stream=ForbiddenBody())

    with pytest.raises(OllamaAdapterError) as captured:
        _run(_embed_with_handler(handler))
    _assert_error(captured.value, OllamaErrorCode.MODEL_PROTOCOL_ERROR)
    assert body_read is False


@pytest.mark.parametrize("header_value", ["bad", "-1", "1025", "1, 1"])
def test_content_length_invalid_or_over_limit_is_protocol_error(header_value: str) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"{}",
            headers={"Content-Length": header_value},
        )

    settings = RuntimeSettings(ollama_max_response_bytes=1024)
    with pytest.raises(OllamaAdapterError) as captured:
        _run(_embed_with_handler(handler, settings=settings))
    _assert_error(captured.value, OllamaErrorCode.MODEL_PROTOCOL_ERROR)


def test_streamed_response_is_bounded_without_content_length() -> None:
    class OversizedStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"{"
            yield b"x" * 1024

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "application/json"},
            stream=OversizedStream(),
        )

    with pytest.raises(OllamaAdapterError) as captured:
        _run(
            _embed_with_handler(
                handler,
                settings=RuntimeSettings(ollama_max_response_bytes=1024),
            )
        )
    _assert_error(captured.value, OllamaErrorCode.MODEL_PROTOCOL_ERROR)


@pytest.mark.parametrize(
    "content",
    [
        b"not-json " + RAW_SENTINEL.encode(),
        b"[]",
        b'{"model":"first","model":"second"}',
        b'{"value":NaN}',
    ],
)
def test_non_json_non_object_duplicate_key_and_nonfinite_json_are_protocol_errors(
    content: bytes,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=content,
            headers={"Content-Type": "application/json"},
        )

    with pytest.raises(OllamaAdapterError) as captured:
        _run(_embed_with_handler(handler))
    _assert_error(captured.value, OllamaErrorCode.MODEL_PROTOCOL_ERROR)


@pytest.mark.parametrize(
    "content_type",
    [
        "application/json; charset=utf-8",
        "APPLICATION/JSON;CHARSET=UTF-8",
        " application/json ; charset = utf-8 ",
    ],
)
def test_success_content_type_accepts_only_json_with_optional_utf8_charset(
    content_type: str,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"model": EMBEDDING_MODEL, "embeddings": [[1.0]]},
            headers={"Content-Type": content_type},
        )

    assert _run(_embed_with_handler(handler)) == ((1.0,),)


@pytest.mark.parametrize(
    "content_type",
    [
        None,
        "text/html",
        "application/problem+json",
        "application/json; charset=latin-1",
        "application/json; charset=utf-8; profile=test",
        "application/json; boundary=test",
    ],
)
def test_success_content_type_drift_is_rejected_before_body_read(
    content_type: str | None,
) -> None:
    body_read = False

    class ForbiddenBody(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            nonlocal body_read
            body_read = True
            raise AssertionError(RAW_SENTINEL)
            yield b""  # pragma: no cover

    async def handler(request: httpx.Request) -> httpx.Response:
        headers = {} if content_type is None else {"Content-Type": content_type}
        return httpx.Response(200, headers=headers, stream=ForbiddenBody())

    with pytest.raises(OllamaAdapterError) as captured:
        _run(_embed_with_handler(handler))
    _assert_error(captured.value, OllamaErrorCode.MODEL_PROTOCOL_ERROR)
    assert body_read is False


def test_duplicate_success_content_type_is_rejected_before_body_read() -> None:
    body_read = False

    class ForbiddenBody(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            nonlocal body_read
            body_read = True
            raise AssertionError(RAW_SENTINEL)
            yield b""  # pragma: no cover

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers=[
                ("Content-Type", "application/json"),
                ("Content-Type", "application/json"),
            ],
            stream=ForbiddenBody(),
        )

    with pytest.raises(OllamaAdapterError) as captured:
        _run(_embed_with_handler(handler))
    _assert_error(captured.value, OllamaErrorCode.MODEL_PROTOCOL_ERROR)
    assert body_read is False


@pytest.mark.parametrize(
    "mutation",
    [
        {"version": "0.12.1", "extra": True},
        {},
        {"version": ""},
        {"version": "v" * 65},
        {"version": 1},
    ],
)
def test_probe_version_is_closed_bounded_string(mutation: dict[str, Any]) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(mutation)

    with pytest.raises(OllamaAdapterError) as captured:
        _run(_probe_with_handler(handler))
    _assert_error(captured.value, OllamaErrorCode.MODEL_PROTOCOL_ERROR)


@pytest.mark.parametrize(
    ("models", "expected"),
    [
        ([], OllamaErrorCode.GENERATION_MODEL_UNAVAILABLE),
        (
            [{"name": GENERATION_MODEL, "model": GENERATION_MODEL, "digest": DIGEST_A}],
            OllamaErrorCode.EMBEDDING_MODEL_UNAVAILABLE,
        ),
        (
            [
                {"name": GENERATION_MODEL, "model": GENERATION_MODEL, "digest": DIGEST_A},
                {"name": GENERATION_MODEL, "model": GENERATION_MODEL, "digest": DIGEST_A},
                {"name": EMBEDDING_MODEL, "model": EMBEDDING_MODEL, "digest": DIGEST_B},
            ],
            OllamaErrorCode.MODEL_PROTOCOL_ERROR,
        ),
        (
            [
                {"name": GENERATION_MODEL, "model": GENERATION_MODEL, "digest": "bad"},
                {"name": EMBEDDING_MODEL, "model": EMBEDDING_MODEL, "digest": DIGEST_B},
            ],
            OllamaErrorCode.MODEL_PROTOCOL_ERROR,
        ),
        (
            [
                {"name": GENERATION_MODEL, "model": "mismatch", "digest": DIGEST_A},
                {"name": EMBEDDING_MODEL, "model": EMBEDDING_MODEL, "digest": DIGEST_B},
            ],
            OllamaErrorCode.MODEL_PROTOCOL_ERROR,
        ),
    ],
)
def test_probe_tags_require_unique_exact_models_and_valid_digests(
    models: list[dict[str, Any]],
    expected: OllamaErrorCode,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return _json_response({"version": "0.12.1"})
        return _json_response({"models": models})

    with pytest.raises(OllamaAdapterError) as captured:
        _run(_probe_with_handler(handler))
    _assert_error(captured.value, expected)


@pytest.mark.parametrize(
    "model_info",
    [
        {},
        {"qwen3.embedding_length": 0},
        {"qwen3.embedding_length": True},
        {"qwen3.embedding_length": 1024, "other.embedding_length": 1024},
    ],
)
def test_show_requires_one_positive_integer_embedding_dimension(
    model_info: dict[str, Any],
) -> None:
    requests: list[httpx.Request] = []
    base_handler = _probe_handler(requests)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/show":
            return _json_response({"model_info": model_info})
        return await base_handler(request)

    with pytest.raises(OllamaAdapterError) as captured:
        _run(_probe_with_handler(handler))
    _assert_error(captured.value, OllamaErrorCode.MODEL_PROTOCOL_ERROR)


def test_show_404_maps_embedding_model_unavailable() -> None:
    requests: list[httpx.Request] = []
    base_handler = _probe_handler(requests)

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/show":
            return httpx.Response(404)
        return await base_handler(request)

    with pytest.raises(OllamaAdapterError) as captured:
        _run(_probe_with_handler(handler))
    _assert_error(captured.value, OllamaErrorCode.EMBEDDING_MODEL_UNAVAILABLE)


@pytest.mark.parametrize(
    "payload",
    [
        {"model": EMBEDDING_MODEL, "embeddings": [[1.0]], "extra": True},
        {"model": EMBEDDING_MODEL},
        {"model": GENERATION_MODEL, "embeddings": [[1.0]]},
        {"model": EMBEDDING_MODEL, "embeddings": []},
        {"model": EMBEDDING_MODEL, "embeddings": [[]]},
        {"model": EMBEDDING_MODEL, "embeddings": [[1.0], [1.0, 2.0]]},
        {"model": EMBEDDING_MODEL, "embeddings": [[True]]},
        {"model": EMBEDDING_MODEL, "embeddings": [[float("nan")]]},
        {"model": EMBEDDING_MODEL, "embeddings": [[float("inf")]]},
    ],
)
def test_embed_rejects_shape_model_count_dimension_and_nonfinite_drift(
    payload: dict[str, Any],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(payload)

    inputs = ("one", "two") if len(payload.get("embeddings", [])) == 2 else ("one",)
    with pytest.raises(OllamaAdapterError) as captured:
        _run(_embed_with_handler(handler, inputs=inputs))
    _assert_error(captured.value, OllamaErrorCode.MODEL_PROTOCOL_ERROR)


def test_embed_expected_dimension_mismatch_is_protocol_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return _json_response({"model": EMBEDDING_MODEL, "embeddings": [[1.0, 2.0]]})

    with pytest.raises(OllamaAdapterError) as captured:
        _run(_embed_with_handler(handler, expected_dimensions=3))
    _assert_error(captured.value, OllamaErrorCode.MODEL_PROTOCOL_ERROR)


@pytest.mark.parametrize(
    "payload",
    [
        {"model": GENERATION_MODEL, "message": {"role": "assistant", "content": "ok"}},
        {"model": GENERATION_MODEL, "message": {"role": "assistant", "content": "ok"}, "done": False},
        {"model": EMBEDDING_MODEL, "message": {"role": "assistant", "content": "ok"}, "done": True},
        {"model": GENERATION_MODEL, "message": {"role": "user", "content": "ok"}, "done": True},
        {"model": GENERATION_MODEL, "message": {"role": "assistant"}, "done": True},
        {"model": GENERATION_MODEL, "message": {"role": "assistant", "content": 1}, "done": True},
        {"model": GENERATION_MODEL, "message": {"role": "assistant", "content": "ok", "tool_calls": []}, "done": True},
        {"model": GENERATION_MODEL, "message": {"role": "assistant", "content": "ok", "thinking": RAW_SENTINEL}, "done": True},
        {"model": GENERATION_MODEL, "message": {"role": "assistant", "content": "ok", "extra": True}, "done": True},
        {"model": GENERATION_MODEL, "message": {"role": "assistant", "content": "ok"}, "done": True, "extra": True},
    ],
)
def test_chat_rejects_missing_extra_model_done_role_content_tools_and_thinking(
    payload: dict[str, Any],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(payload)

    with pytest.raises(OllamaAdapterError) as captured:
        _run(_chat_with_handler(handler))
    _assert_error(captured.value, OllamaErrorCode.MODEL_PROTOCOL_ERROR)


@pytest.mark.parametrize(
    "inputs",
    [
        (),
        [],
        ("",),
        (" ",),
        ("x" * 8193,),
        tuple("x" for _ in range(65)),
        tuple("x" * 8192 for _ in range(9)),
    ],
)
def test_embed_input_bounds_fail_before_transport(inputs: Any) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response({})

    with pytest.raises(ValueError, match="Ollama adapter input is invalid"):
        _run(_embed_with_handler(handler, inputs=inputs))
    assert calls == 0


@pytest.mark.parametrize("expected_dimensions", [0, -1, True, 1.5])
def test_embed_expected_dimension_bounds_fail_before_transport(expected_dimensions: Any) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response({})

    with pytest.raises(ValueError, match="Ollama adapter input is invalid"):
        _run(_embed_with_handler(handler, expected_dimensions=expected_dimensions))
    assert calls == 0


def test_chat_message_closure_and_input_bounds_fail_before_transport() -> None:
    with pytest.raises(ValidationError):
        OllamaMessage.model_validate({"role": "assistant", "content": "x"})
    with pytest.raises(ValidationError):
        OllamaMessage.model_validate({"role": "user", "content": "x", "extra": RAW_SENTINEL})
    with pytest.raises(ValidationError):
        OllamaMessage(role="user", content=" ")

    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json_response({})

    invalid_messages: tuple[Any, ...] = (
        (),
        [],
        tuple(OllamaMessage(role="user", content="x") for _ in range(17)),
        (OllamaMessage(role="user", content="x" * 32768),) * 3,
        ({"role": "user", "content": "x"},),
    )
    for messages in invalid_messages:
        with pytest.raises(ValueError, match="Ollama adapter input is invalid"):
            _run(_chat_with_handler(handler, messages=messages))
    assert calls == 0


def test_unexpected_transport_exception_is_minimized_protocol_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError(RAW_SENTINEL + " http://malicious.invalid/path")

    with pytest.raises(OllamaAdapterError) as captured:
        _run(
            _chat_with_handler(
                handler,
                messages=(OllamaMessage(role="user", content=RAW_SENTINEL),),
            )
        )
    _assert_error(captured.value, OllamaErrorCode.MODEL_PROTOCOL_ERROR)


def test_cancellation_is_never_converted_or_swallowed() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        _run(_embed_with_handler(handler))


def test_factory_build_and_close_exceptions_are_content_free() -> None:
    def broken_factory(**kwargs: Any) -> httpx.AsyncClient:
        raise RuntimeError(RAW_SENTINEL + " http://malicious.invalid/factory")

    with pytest.raises(OllamaAdapterError) as factory_error:
        OllamaClient(RuntimeSettings(), client_factory=broken_factory)
    _assert_error(factory_error.value, OllamaErrorCode.MODEL_PROTOCOL_ERROR)

    class BrokenClient(httpx.AsyncClient):
        def build_request(self, *args: Any, **kwargs: Any) -> httpx.Request:
            raise RuntimeError(RAW_SENTINEL + " http://malicious.invalid/build")

        async def aclose(self) -> None:
            raise RuntimeError(RAW_SENTINEL + " http://malicious.invalid/close")

    def broken_client_factory(**kwargs: Any) -> httpx.AsyncClient:
        return BrokenClient(**kwargs)

    async def exercise() -> tuple[OllamaAdapterError, OllamaAdapterError]:
        client = OllamaClient(RuntimeSettings(), client_factory=broken_client_factory)
        try:
            await client.embed(("synthetic",))
        except OllamaAdapterError as error:
            build_error = error
        try:
            await client.aclose()
        except OllamaAdapterError as error:
            close_error = error
        return build_error, close_error

    for error in _run(exercise()):
        _assert_error(error, OllamaErrorCode.MODEL_PROTOCOL_ERROR)
