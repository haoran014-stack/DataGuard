"""Content-free failures for vector-index parsing, binding, and retrieval."""

from __future__ import annotations

from enum import Enum
from typing import NoReturn


class VectorIndexErrorCode(str, Enum):
    """Stable internal codes that never contain artifact or corpus values."""

    INVALID_INPUT = "vector_index_invalid_input"
    INVALID_ARTIFACT = "vector_index_invalid_artifact"
    BINDING_MISMATCH = "vector_index_binding_mismatch"
    INVALID_QUERY = "vector_index_invalid_query"


_SAFE_MESSAGES: dict[VectorIndexErrorCode, str] = {
    VectorIndexErrorCode.INVALID_INPUT: "Vector index input is invalid.",
    VectorIndexErrorCode.INVALID_ARTIFACT: "Vector index artifact is invalid.",
    VectorIndexErrorCode.BINDING_MISMATCH: "Vector index binding does not match.",
    VectorIndexErrorCode.INVALID_QUERY: "Vector index query is invalid.",
}


class VectorIndexError(Exception):
    """A fixed error that retains no raw bytes, vector, document, or path."""

    __slots__ = ("code", "message")

    def __init__(self, code: VectorIndexErrorCode) -> None:
        if not isinstance(code, VectorIndexErrorCode):
            raise TypeError("Vector index error code is invalid")
        self.code = code
        self.message = _SAFE_MESSAGES[code]
        super().__init__(self.message)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "message": self.message}


def raise_vector_index_error(code: VectorIndexErrorCode) -> NoReturn:
    raise VectorIndexError(code) from None
