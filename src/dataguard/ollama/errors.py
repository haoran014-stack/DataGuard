"""Content-free domain failures for the local Ollama adapter."""

from __future__ import annotations

from enum import Enum
from typing import NoReturn


class OllamaErrorCode(str, Enum):
    """The only stable error codes emitted by this adapter."""

    OLLAMA_UNAVAILABLE = "ollama_unavailable"
    GENERATION_MODEL_UNAVAILABLE = "generation_model_unavailable"
    EMBEDDING_MODEL_UNAVAILABLE = "embedding_model_unavailable"
    MODEL_TIMEOUT = "model_timeout"
    MODEL_PROTOCOL_ERROR = "model_protocol_error"


_SAFE_MESSAGES: dict[OllamaErrorCode, str] = {
    OllamaErrorCode.OLLAMA_UNAVAILABLE: "The local Ollama runtime is unavailable.",
    OllamaErrorCode.GENERATION_MODEL_UNAVAILABLE: (
        "The required local generation model is unavailable."
    ),
    OllamaErrorCode.EMBEDDING_MODEL_UNAVAILABLE: (
        "The required local embedding model is unavailable."
    ),
    OllamaErrorCode.MODEL_TIMEOUT: "The local model request timed out.",
    OllamaErrorCode.MODEL_PROTOCOL_ERROR: (
        "The local model returned an invalid bounded response."
    ),
}


class OllamaAdapterError(Exception):
    """A fixed, serializable adapter failure that never embeds raw input."""

    __slots__ = ("code", "message")

    def __init__(self, code: OllamaErrorCode) -> None:
        if not isinstance(code, OllamaErrorCode):
            raise TypeError("Ollama adapter error code is invalid")
        self.code = code
        self.message = _SAFE_MESSAGES[code]
        super().__init__(self.message)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "message": self.message}


def raise_ollama_error(code: OllamaErrorCode) -> NoReturn:
    """Raise a content-free failure without retaining a lower-level exception."""

    raise OllamaAdapterError(code) from None
