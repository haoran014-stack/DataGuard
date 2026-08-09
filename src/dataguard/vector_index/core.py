"""Explicit vector-index build, binding, and deterministic retrieval core."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from pydantic import ValidationError

from dataguard.domain import Corpus, Document
from dataguard.ollama import OllamaClient, OllamaHealthFacts
from dataguard.vector_index.errors import VectorIndexErrorCode, raise_vector_index_error
from dataguard.vector_index.models import (
    DOCUMENT_COUNT,
    EMBEDDING_MODEL_TAG,
    MAX_VECTOR_DIMENSIONS,
    RETRIEVAL_TOP_K,
    VECTOR_INDEX_FORMAT,
    RetrievalResult,
    VectorIndexArtifact,
    VectorIndexEntry,
)


_RAW_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_VALIDATED_TOKEN = object()


def document_embedding_input(document: Document) -> str:
    """Return the exact v1 transient embedding input without metadata append."""

    if not isinstance(document, Document):
        raise_vector_index_error(VectorIndexErrorCode.INVALID_INPUT)
    return document.title + "\n\n" + document.content


async def build_vector_index(
    corpus: Corpus,
    corpus_sha256: str,
    health: OllamaHealthFacts,
    client: OllamaClient,
) -> VectorIndexArtifact:
    """Embed the accepted corpus in one ordered, bounded 30-document request."""

    if (
        not isinstance(corpus, Corpus)
        or type(corpus_sha256) is not str
        or _RAW_SHA256.fullmatch(corpus_sha256) is None
        or not isinstance(health, OllamaHealthFacts)
        or not isinstance(client, OllamaClient)
        or not 1 <= health.embedding_dimensions <= MAX_VECTOR_DIMENSIONS
    ):
        raise_vector_index_error(VectorIndexErrorCode.INVALID_INPUT)

    document_ids = tuple(document.doc_id for document in corpus.documents)
    if len(document_ids) != DOCUMENT_COUNT or len(set(document_ids)) != DOCUMENT_COUNT:
        raise_vector_index_error(VectorIndexErrorCode.INVALID_INPUT)

    inputs = tuple(document_embedding_input(document) for document in corpus.documents)
    vectors = await client.embed(inputs, expected_dimensions=health.embedding_dimensions)
    if len(vectors) != DOCUMENT_COUNT:
        raise_vector_index_error(VectorIndexErrorCode.INVALID_INPUT)

    entries: list[VectorIndexEntry] = []
    for document, vector in zip(corpus.documents, vectors, strict=True):
        try:
            entries.append(VectorIndexEntry(doc_id=document.doc_id, vector=vector))
        except ValidationError:
            raise_vector_index_error(VectorIndexErrorCode.INVALID_INPUT)

    try:
        return VectorIndexArtifact(
            format=VECTOR_INDEX_FORMAT,
            corpus_version=corpus.corpus_version,
            corpus_sha256=corpus_sha256,
            ordered_document_ids=document_ids,
            embedding_model_tag=health.embedding_model.tag,
            embedding_model_digest=health.embedding_model.digest,
            dimensions=health.embedding_dimensions,
            entries=tuple(entries),
        )
    except ValidationError:
        raise_vector_index_error(VectorIndexErrorCode.INVALID_INPUT)


@dataclass(frozen=True, slots=True, repr=False, init=False)
class ValidatedVectorIndex:
    """Opaque binding-validated retrieval handle with a vector-free repr."""

    _artifact: VectorIndexArtifact
    _norms: tuple[float, ...]

    def __init__(
        self,
        artifact: VectorIndexArtifact,
        norms: tuple[float, ...],
        *,
        _token: object,
    ) -> None:
        if _token is not _VALIDATED_TOKEN:
            raise_vector_index_error(VectorIndexErrorCode.BINDING_MISMATCH)
        object.__setattr__(self, "_artifact", artifact)
        object.__setattr__(self, "_norms", norms)

    @property
    def dimensions(self) -> int:
        return self._artifact.dimensions

    @property
    def document_count(self) -> int:
        return len(self._artifact.entries)

    def __repr__(self) -> str:
        return (
            "ValidatedVectorIndex("
            f"format={self._artifact.format!r}, "
            f"documents={self.document_count}, dimensions={self.dimensions})"
        )


def validate_vector_index_binding(
    artifact: VectorIndexArtifact,
    corpus: Corpus,
    corpus_sha256: str,
    health: OllamaHealthFacts,
) -> ValidatedVectorIndex:
    """Bind an artifact to accepted corpus bytes and probed local model facts."""

    if (
        not isinstance(artifact, VectorIndexArtifact)
        or not isinstance(corpus, Corpus)
        or type(corpus_sha256) is not str
        or _RAW_SHA256.fullmatch(corpus_sha256) is None
        or not isinstance(health, OllamaHealthFacts)
        or not 1 <= health.embedding_dimensions <= MAX_VECTOR_DIMENSIONS
    ):
        raise_vector_index_error(VectorIndexErrorCode.BINDING_MISMATCH)

    try:
        artifact = VectorIndexArtifact.model_validate(artifact.model_dump(mode="python"))
    except (ValidationError, TypeError, ValueError):
        raise_vector_index_error(VectorIndexErrorCode.BINDING_MISMATCH)

    document_ids = tuple(document.doc_id for document in corpus.documents)
    expected = (
        artifact.format == VECTOR_INDEX_FORMAT
        and artifact.corpus_version == corpus.corpus_version
        and artifact.corpus_sha256 == corpus_sha256
        and artifact.ordered_document_ids == document_ids
        and tuple(entry.doc_id for entry in artifact.entries) == document_ids
        and artifact.embedding_model_tag == EMBEDDING_MODEL_TAG
        and artifact.embedding_model_tag == health.embedding_model.tag
        and artifact.embedding_model_digest == health.embedding_model.digest
        and artifact.dimensions == health.embedding_dimensions
        and len(document_ids) == DOCUMENT_COUNT
        and len(set(document_ids)) == DOCUMENT_COUNT
    )
    if not expected:
        raise_vector_index_error(VectorIndexErrorCode.BINDING_MISMATCH)

    norms = tuple(math.hypot(*entry.vector) for entry in artifact.entries)
    if any(not math.isfinite(norm) or norm == 0.0 for norm in norms):
        raise_vector_index_error(VectorIndexErrorCode.BINDING_MISMATCH)
    return ValidatedVectorIndex(artifact, norms, _token=_VALIDATED_TOKEN)


def _validated_query(query_vector: object, dimensions: int) -> tuple[tuple[float, ...], float]:
    if type(query_vector) is not tuple or len(query_vector) != dimensions:
        raise_vector_index_error(VectorIndexErrorCode.INVALID_QUERY)
    converted: list[float] = []
    for value in query_vector:
        if type(value) not in {int, float} or not math.isfinite(value):
            raise_vector_index_error(VectorIndexErrorCode.INVALID_QUERY)
        converted.append(float(value))
    norm = math.hypot(*converted)
    if not math.isfinite(norm) or norm == 0.0:
        raise_vector_index_error(VectorIndexErrorCode.INVALID_QUERY)
    return tuple(converted), norm


def retrieve(
    index: ValidatedVectorIndex,
    query_vector: tuple[float, ...],
    eligible_document_ids: tuple[str, ...],
) -> tuple[RetrievalResult, ...]:
    """Cosine-rank only the caller-provided eligible set, deterministically."""

    if not isinstance(index, ValidatedVectorIndex):
        raise_vector_index_error(VectorIndexErrorCode.BINDING_MISMATCH)
    query, query_norm = _validated_query(query_vector, index.dimensions)
    if (
        type(eligible_document_ids) is not tuple
        or len(eligible_document_ids) > DOCUMENT_COUNT
        or any(type(doc_id) is not str for doc_id in eligible_document_ids)
        or len(set(eligible_document_ids)) != len(eligible_document_ids)
    ):
        raise_vector_index_error(VectorIndexErrorCode.INVALID_QUERY)

    eligible = set(eligible_document_ids)
    known = set(index._artifact.ordered_document_ids)
    if not eligible.issubset(known):
        raise_vector_index_error(VectorIndexErrorCode.INVALID_QUERY)

    normalized_query = tuple(value / query_norm for value in query)
    scored: list[RetrievalResult] = []
    for entry, vector_norm in zip(index._artifact.entries, index._norms, strict=True):
        if entry.doc_id not in eligible:
            continue
        score = math.fsum(
            query_value * (vector_value / vector_norm)
            for query_value, vector_value in zip(normalized_query, entry.vector, strict=True)
        )
        if not math.isfinite(score):
            raise_vector_index_error(VectorIndexErrorCode.INVALID_QUERY)
        score = max(-1.0, min(1.0, score))
        scored.append(RetrievalResult(doc_id=entry.doc_id, similarity_score=score))

    scored.sort(key=lambda item: (-item.similarity_score, item.doc_id))
    return tuple(scored[:RETRIEVAL_TOP_K])
