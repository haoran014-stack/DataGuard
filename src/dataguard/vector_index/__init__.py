"""Versioned in-memory vector-index core with explicit validated retrieval."""

from dataguard.vector_index.canonical import (
    canonical_vector_index_bytes,
    load_canonical_vector_index,
    vector_index_sha256,
)
from dataguard.vector_index.core import (
    ValidatedVectorIndex,
    build_vector_index,
    document_embedding_input,
    retrieve,
    validate_vector_index_binding,
)
from dataguard.vector_index.errors import VectorIndexError, VectorIndexErrorCode
from dataguard.vector_index.models import (
    MAX_CANONICAL_ARTIFACT_BYTES,
    MAX_VECTOR_DIMENSIONS,
    RETRIEVAL_TOP_K,
    VECTOR_INDEX_FORMAT,
    RetrievalResult,
    VectorIndexArtifact,
    VectorIndexEntry,
)
from dataguard.vector_index.store import (
    INDEX_FILENAME,
    LoadedVectorIndex,
    StoredIndexErrorCode,
    StoredIndexFacts,
    StoredIndexState,
    VectorIndexStore,
    VectorIndexStoreError,
)

__all__ = [
    "MAX_CANONICAL_ARTIFACT_BYTES",
    "MAX_VECTOR_DIMENSIONS",
    "INDEX_FILENAME",
    "LoadedVectorIndex",
    "RETRIEVAL_TOP_K",
    "VECTOR_INDEX_FORMAT",
    "RetrievalResult",
    "StoredIndexErrorCode",
    "StoredIndexFacts",
    "StoredIndexState",
    "ValidatedVectorIndex",
    "VectorIndexArtifact",
    "VectorIndexEntry",
    "VectorIndexError",
    "VectorIndexErrorCode",
    "VectorIndexStore",
    "VectorIndexStoreError",
    "build_vector_index",
    "canonical_vector_index_bytes",
    "document_embedding_input",
    "load_canonical_vector_index",
    "retrieve",
    "validate_vector_index_binding",
    "vector_index_sha256",
]
