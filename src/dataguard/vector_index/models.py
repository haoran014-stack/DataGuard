"""Closed immutable values for the versioned vector-index artifact."""

from __future__ import annotations

import math
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


VECTOR_INDEX_FORMAT = "dataguard-vector-index-v1"
EMBEDDING_MODEL_TAG = "qwen3-embedding:0.6b"
DOCUMENT_COUNT = 30
MAX_VECTOR_DIMENSIONS = 16_384
MAX_CANONICAL_ARTIFACT_BYTES = 64 * 1_024 * 1_024
RETRIEVAL_TOP_K = 4

IndexId = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)]
Sha256Digest = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^(?:sha256:)?[a-f0-9]{64}$"),
]
RawSha256Digest = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[a-f0-9]{64}$"),
]


class _ClosedFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )


def _validated_vector(value: object) -> tuple[float, ...]:
    if (
        type(value) not in {list, tuple}
        or not value
        or len(value) > MAX_VECTOR_DIMENSIONS
    ):
        raise ValueError("vector must be a non-empty finite numeric sequence")
    converted: list[float] = []
    for item in value:
        if type(item) not in {int, float} or not math.isfinite(item):
            raise ValueError("vector must be a non-empty finite numeric sequence")
        converted.append(float(item))
    norm = math.hypot(*converted)
    if not math.isfinite(norm) or norm == 0.0:
        raise ValueError("vector norm must be finite and non-zero")
    return tuple(converted)


class VectorIndexEntry(_ClosedFrozenModel):
    doc_id: IndexId
    vector: tuple[float, ...] = Field(repr=False)

    @field_validator("vector", mode="before")
    @classmethod
    def validate_vector(cls, value: object) -> tuple[float, ...]:
        return _validated_vector(value)


class VectorIndexArtifact(_ClosedFrozenModel):
    """Internal artifact model; its dump intentionally contains numeric vectors."""

    format: Literal["dataguard-vector-index-v1"]
    corpus_version: Literal["synthetic-v1"]
    corpus_sha256: RawSha256Digest
    ordered_document_ids: tuple[IndexId, ...] = Field(
        min_length=DOCUMENT_COUNT,
        max_length=DOCUMENT_COUNT,
        repr=False,
    )
    embedding_model_tag: Literal["qwen3-embedding:0.6b"]
    embedding_model_digest: Sha256Digest
    dimensions: int = Field(strict=True, ge=1, le=MAX_VECTOR_DIMENSIONS)
    entries: tuple[VectorIndexEntry, ...] = Field(
        min_length=DOCUMENT_COUNT,
        max_length=DOCUMENT_COUNT,
        repr=False,
    )

    @model_validator(mode="after")
    def require_locked_order_and_dimensions(self) -> Self:
        if len(set(self.ordered_document_ids)) != DOCUMENT_COUNT:
            raise ValueError("ordered document identifiers must be unique")
        entry_ids = tuple(entry.doc_id for entry in self.entries)
        if entry_ids != self.ordered_document_ids:
            raise ValueError("entry identifiers must match the ordered document identifiers")
        if any(len(entry.vector) != self.dimensions for entry in self.entries):
            raise ValueError("every vector must match the declared dimensions")
        return self


class RetrievalResult(_ClosedFrozenModel):
    """Minimized retrieval evidence; never contains text or a vector."""

    doc_id: IndexId
    similarity_score: float = Field(strict=True, ge=-1.0, le=1.0)

    @field_validator("similarity_score")
    @classmethod
    def require_finite_score(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("similarity score must be finite")
        return value
