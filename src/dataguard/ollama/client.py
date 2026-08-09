"""Async, bounded adapter for the separately managed loopback Ollama runtime."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping
from typing import Any, Literal, TypeAlias

import httpx

from dataguard.config import RuntimeSettings
from dataguard.ollama.errors import OllamaErrorCode, raise_ollama_error
from dataguard.ollama.models import OllamaHealthFacts, OllamaMessage, OllamaModelFacts


GENERATION_MODEL = "qwen2.5:3b-instruct"
EMBEDDING_MODEL = "qwen3-embedding:0.6b"

MAX_TAG_RECORDS = 1_024
MAX_MODEL_INFO_FIELDS = 4_096
MAX_EMBED_INPUTS = 64
MAX_EMBED_INPUT_CHARS = 8_192
MAX_EMBED_TOTAL_CHARS = 65_536
MAX_CHAT_MESSAGES = 16
MAX_CHAT_TOTAL_CHARS = 65_536

_DIGEST_PATTERN = re.compile(r"^(?:sha256:)?[a-f0-9]{64}$")
_CONTENT_LENGTH_PATTERN = re.compile(r"^[0-9]+$")

_TAG_ENTRY_FIELDS = frozenset(
    {"name", "model", "modified_at", "size", "digest", "details"}
)
_SHOW_FIELDS = frozenset(
    {
        "license",
        "modelfile",
        "parameters",
        "template",
        "details",
        "model_info",
        "capabilities",
        "modified_at",
    }
)
_EMBED_FIELDS = frozenset(
    {"model", "embeddings", "total_duration", "load_duration", "prompt_eval_count"}
)
_CHAT_FIELDS = frozenset(
    {
        "model",
        "created_at",
        "message",
        "done",
        "done_reason",
        "total_duration",
        "load_duration",
        "prompt_eval_count",
        "prompt_eval_duration",
        "eval_count",
        "eval_duration",
    }
)
_CHAT_MESSAGE_FIELDS = frozenset({"role", "content", "thinking"})

AsyncClientFactory: TypeAlias = Callable[..., httpx.AsyncClient]
Model404Code: TypeAlias = Literal[
    OllamaErrorCode.GENERATION_MODEL_UNAVAILABLE,
    OllamaErrorCode.EMBEDDING_MODEL_UNAVAILABLE,
]


def _invalid_input() -> ValueError:
    return ValueError("Ollama adapter input is invalid")


def _raise_protocol() -> None:
    raise_ollama_error(OllamaErrorCode.MODEL_PROTOCOL_ERROR)


def _closed_object(
    value: Any,
    *,
    required: frozenset[str],
    allowed: frozenset[str],
) -> dict[str, Any]:
    if type(value) is not dict or not required.issubset(value) or not set(value).issubset(allowed):
        _raise_protocol()
    return value


def _nonnegative_integer(value: Any) -> bool:
    return type(value) is int and value >= 0


def _validate_optional_protocol_fields(
    payload: Mapping[str, Any],
    *,
    string_fields: tuple[str, ...] = (),
    integer_fields: tuple[str, ...] = (),
) -> None:
    for field in string_fields:
        if field in payload and type(payload[field]) is not str:
            _raise_protocol()
    for field in integer_fields:
        if field in payload and not _nonnegative_integer(payload[field]):
            _raise_protocol()


def _reject_json_constant(_: str) -> None:
    raise ValueError


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _decode_json_object(raw: bytes) -> dict[str, Any]:
    try:
        decoded = raw.decode("utf-8")
        value = json.loads(
            decoded,
            parse_constant=_reject_json_constant,
            object_pairs_hook=_unique_json_object,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, TypeError):
        _raise_protocol()
    if type(value) is not dict:
        _raise_protocol()
    return value


class OllamaClient:
    """Explicit-lifecycle client for only the configured loopback Ollama root."""

    def __init__(
        self,
        settings: RuntimeSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        client_factory: AsyncClientFactory = httpx.AsyncClient,
    ) -> None:
        if not isinstance(settings, RuntimeSettings):
            raise TypeError("Ollama client settings are invalid")
        timeout = httpx.Timeout(
            connect=settings.ollama_connect_timeout_seconds,
            read=settings.ollama_read_timeout_seconds,
            write=settings.ollama_read_timeout_seconds,
            pool=settings.ollama_connect_timeout_seconds,
        )
        self._max_response_bytes = settings.ollama_max_response_bytes
        try:
            self._client = client_factory(
                base_url=settings.ollama_base_url,
                timeout=timeout,
                transport=transport,
                follow_redirects=False,
                headers={"Accept": "application/json"},
            )
        except Exception:
            _raise_protocol()
        if not isinstance(self._client, httpx.AsyncClient):
            raise TypeError("Ollama async client factory is invalid")

    async def __aenter__(self) -> OllamaClient:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        try:
            await self._client.aclose()
        except Exception:
            _raise_protocol()

    async def _request_json(
        self,
        method: Literal["GET", "POST"],
        path: Literal["/api/version", "/api/tags", "/api/show", "/api/embed", "/api/chat"],
        *,
        body: dict[str, Any] | None = None,
        model_404_code: Model404Code | None = None,
        timeout_code: OllamaErrorCode,
    ) -> dict[str, Any]:
        request_kwargs: dict[str, Any] = {"headers": {"Accept": "application/json"}}
        if body is not None:
            request_kwargs["json"] = body
        try:
            request = self._client.build_request(method, path, **request_kwargs)
            response = await self._client.send(request, stream=True)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise_ollama_error(OllamaErrorCode.OLLAMA_UNAVAILABLE)
        except httpx.TimeoutException:
            raise_ollama_error(timeout_code)
        except Exception:
            _raise_protocol()

        try:
            lengths = response.headers.get_list("content-length")
            if len(lengths) > 1:
                _raise_protocol()
            if lengths:
                rendered_length = lengths[0]
                if not _CONTENT_LENGTH_PATTERN.fullmatch(rendered_length):
                    _raise_protocol()
                if int(rendered_length) > self._max_response_bytes:
                    _raise_protocol()

            if response.status_code == 404 and model_404_code is not None:
                raise_ollama_error(model_404_code)
            if response.status_code < 200 or response.status_code >= 300:
                _raise_protocol()

            content_types = response.headers.get_list("content-type")
            if len(content_types) != 1 or re.fullmatch(
                r"\s*application/json\s*(?:;\s*charset\s*=\s*utf-8\s*)?",
                content_types[0],
                flags=re.IGNORECASE,
            ) is None:
                _raise_protocol()

            raw = bytearray()
            try:
                async for chunk in response.aiter_bytes():
                    if len(raw) + len(chunk) > self._max_response_bytes:
                        _raise_protocol()
                    raw.extend(chunk)
            except (httpx.ConnectError, httpx.ConnectTimeout):
                raise_ollama_error(OllamaErrorCode.OLLAMA_UNAVAILABLE)
            except httpx.TimeoutException:
                raise_ollama_error(timeout_code)
            except Exception:
                _raise_protocol()
            return _decode_json_object(bytes(raw))
        finally:
            try:
                await response.aclose()
            except Exception:
                pass

    async def probe(self) -> OllamaHealthFacts:
        """Return minimized facts required by the later health service."""

        version_payload = await self._request_json(
            "GET",
            "/api/version",
            timeout_code=OllamaErrorCode.OLLAMA_UNAVAILABLE,
        )
        _closed_object(
            version_payload,
            required=frozenset({"version"}),
            allowed=frozenset({"version"}),
        )
        version = version_payload["version"]
        if type(version) is not str or not version or version != version.strip() or len(version) > 64:
            _raise_protocol()

        tags_payload = await self._request_json(
            "GET",
            "/api/tags",
            timeout_code=OllamaErrorCode.OLLAMA_UNAVAILABLE,
        )
        _closed_object(
            tags_payload,
            required=frozenset({"models"}),
            allowed=frozenset({"models"}),
        )
        models = tags_payload["models"]
        if type(models) is not list or len(models) > MAX_TAG_RECORDS:
            _raise_protocol()
        found: dict[str, str] = {}
        for entry_value in models:
            entry = _closed_object(
                entry_value,
                required=frozenset({"name", "model", "digest"}),
                allowed=_TAG_ENTRY_FIELDS,
            )
            name = entry["name"]
            model = entry["model"]
            digest = entry["digest"]
            if (
                type(name) is not str
                or type(model) is not str
                or not name
                or len(name) > 64
                or name != model
                or type(digest) is not str
                or _DIGEST_PATTERN.fullmatch(digest) is None
            ):
                _raise_protocol()
            _validate_optional_protocol_fields(
                entry,
                string_fields=("modified_at",),
                integer_fields=("size",),
            )
            if "details" in entry and type(entry["details"]) is not dict:
                _raise_protocol()
            if name in {GENERATION_MODEL, EMBEDDING_MODEL}:
                if name in found:
                    _raise_protocol()
                found[name] = digest

        if GENERATION_MODEL not in found:
            raise_ollama_error(OllamaErrorCode.GENERATION_MODEL_UNAVAILABLE)
        if EMBEDDING_MODEL not in found:
            raise_ollama_error(OllamaErrorCode.EMBEDDING_MODEL_UNAVAILABLE)

        show_payload = await self._request_json(
            "POST",
            "/api/show",
            body={"model": EMBEDDING_MODEL, "verbose": False},
            model_404_code=OllamaErrorCode.EMBEDDING_MODEL_UNAVAILABLE,
            timeout_code=OllamaErrorCode.OLLAMA_UNAVAILABLE,
        )
        show = _closed_object(
            show_payload,
            required=frozenset({"model_info"}),
            allowed=_SHOW_FIELDS,
        )
        model_info = show["model_info"]
        if type(model_info) is not dict or len(model_info) > MAX_MODEL_INFO_FIELDS:
            _raise_protocol()
        dimension_values = [
            value
            for key, value in model_info.items()
            if type(key) is str and key.endswith(".embedding_length")
        ]
        if (
            len(dimension_values) != 1
            or type(dimension_values[0]) is not int
            or dimension_values[0] <= 0
        ):
            _raise_protocol()
        _validate_optional_protocol_fields(
            show,
            string_fields=("license", "modelfile", "parameters", "template", "modified_at"),
        )
        if "details" in show and type(show["details"]) is not dict:
            _raise_protocol()
        if "capabilities" in show and (
            type(show["capabilities"]) is not list
            or any(type(value) is not str for value in show["capabilities"])
        ):
            _raise_protocol()

        return OllamaHealthFacts(
            version=version,
            generation_model=OllamaModelFacts(
                tag=GENERATION_MODEL,
                digest=found[GENERATION_MODEL],
            ),
            embedding_model=OllamaModelFacts(
                tag=EMBEDDING_MODEL,
                digest=found[EMBEDDING_MODEL],
            ),
            embedding_dimensions=dimension_values[0],
        )

    async def embed(
        self,
        inputs: tuple[str, ...],
        *,
        expected_dimensions: int | None = None,
    ) -> tuple[tuple[float, ...], ...]:
        """Create finite, dimension-consistent embeddings without truncation."""

        if (
            type(inputs) is not tuple
            or not 1 <= len(inputs) <= MAX_EMBED_INPUTS
            or any(
                type(value) is not str
                or value == ""
                or len(value) > MAX_EMBED_INPUT_CHARS
                for value in inputs
            )
            or sum(len(value) for value in inputs) > MAX_EMBED_TOTAL_CHARS
            or (
                expected_dimensions is not None
                and (type(expected_dimensions) is not int or expected_dimensions <= 0)
            )
        ):
            raise _invalid_input()

        payload = await self._request_json(
            "POST",
            "/api/embed",
            body={"model": EMBEDDING_MODEL, "input": list(inputs), "truncate": False},
            model_404_code=OllamaErrorCode.EMBEDDING_MODEL_UNAVAILABLE,
            timeout_code=OllamaErrorCode.MODEL_TIMEOUT,
        )
        embed_payload = _closed_object(
            payload,
            required=frozenset({"model", "embeddings"}),
            allowed=_EMBED_FIELDS,
        )
        if embed_payload["model"] != EMBEDDING_MODEL:
            _raise_protocol()
        _validate_optional_protocol_fields(
            embed_payload,
            integer_fields=("total_duration", "load_duration", "prompt_eval_count"),
        )
        embeddings = embed_payload["embeddings"]
        if type(embeddings) is not list or len(embeddings) != len(inputs):
            _raise_protocol()

        result: list[tuple[float, ...]] = []
        dimensions: int | None = None
        for vector in embeddings:
            if type(vector) is not list or not vector:
                _raise_protocol()
            converted: list[float] = []
            for value in vector:
                if type(value) not in {int, float} or not math.isfinite(value):
                    _raise_protocol()
                converted.append(float(value))
            if dimensions is None:
                dimensions = len(converted)
            elif len(converted) != dimensions:
                _raise_protocol()
            result.append(tuple(converted))

        if expected_dimensions is not None and dimensions != expected_dimensions:
            _raise_protocol()
        return tuple(result)

    async def chat(self, messages: tuple[OllamaMessage, ...]) -> str:
        """Generate one non-streaming assistant response without tools or thinking."""

        if (
            type(messages) is not tuple
            or not 1 <= len(messages) <= MAX_CHAT_MESSAGES
            or any(not isinstance(message, OllamaMessage) for message in messages)
            or sum(len(message.content) for message in messages) > MAX_CHAT_TOTAL_CHARS
        ):
            raise _invalid_input()

        payload = await self._request_json(
            "POST",
            "/api/chat",
            body={
                "model": GENERATION_MODEL,
                "messages": [message.model_dump(mode="json") for message in messages],
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
            },
            model_404_code=OllamaErrorCode.GENERATION_MODEL_UNAVAILABLE,
            timeout_code=OllamaErrorCode.MODEL_TIMEOUT,
        )
        chat_payload = _closed_object(
            payload,
            required=frozenset({"model", "message", "done"}),
            allowed=_CHAT_FIELDS,
        )
        if chat_payload["model"] != GENERATION_MODEL or chat_payload["done"] is not True:
            _raise_protocol()
        _validate_optional_protocol_fields(
            chat_payload,
            string_fields=("created_at", "done_reason"),
            integer_fields=(
                "total_duration",
                "load_duration",
                "prompt_eval_count",
                "prompt_eval_duration",
                "eval_count",
                "eval_duration",
            ),
        )
        message = chat_payload["message"]
        if type(message) is not dict or "tool_calls" in message:
            _raise_protocol()
        message = _closed_object(
            message,
            required=frozenset({"role", "content"}),
            allowed=_CHAT_MESSAGE_FIELDS,
        )
        if (
            message["role"] != "assistant"
            or type(message["content"]) is not str
            or ("thinking" in message and message["thinking"] != "")
        ):
            _raise_protocol()
        return message["content"]
