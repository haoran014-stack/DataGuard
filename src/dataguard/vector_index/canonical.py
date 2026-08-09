"""Canonical in-memory JSON codec for the v1 vector-index artifact."""

from __future__ import annotations

import codecs
import hashlib
import json
from typing import Any

from pydantic import ValidationError

from dataguard.vector_index.errors import VectorIndexErrorCode, raise_vector_index_error
from dataguard.vector_index.models import (
    MAX_CANONICAL_ARTIFACT_BYTES,
    VectorIndexArtifact,
)


class _DuplicateKeyError(ValueError):
    pass


def _closed_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _reject_nonfinite(_: str) -> None:
    raise ValueError


def canonical_vector_index_bytes(artifact: VectorIndexArtifact) -> bytes:
    """Serialize one validated artifact to the exact S2-CD04 byte form."""

    if not isinstance(artifact, VectorIndexArtifact):
        raise_vector_index_error(VectorIndexErrorCode.INVALID_INPUT)
    try:
        artifact = VectorIndexArtifact.model_validate(artifact.model_dump(mode="python"))
        encoded = json.dumps(
            artifact.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8") + b"\n"
    except (TypeError, ValueError, UnicodeError, ValidationError):
        raise_vector_index_error(VectorIndexErrorCode.INVALID_ARTIFACT)
    if len(encoded) > MAX_CANONICAL_ARTIFACT_BYTES:
        raise_vector_index_error(VectorIndexErrorCode.INVALID_ARTIFACT)
    return encoded


def vector_index_sha256(raw: bytes) -> str:
    if type(raw) is not bytes:
        raise_vector_index_error(VectorIndexErrorCode.INVALID_INPUT)
    load_canonical_vector_index(raw)
    return hashlib.sha256(raw).hexdigest()


def load_canonical_vector_index(raw: bytes) -> VectorIndexArtifact:
    """Accept only exact canonical bytes; never retain or echo rejected input."""

    if type(raw) is not bytes or not raw or len(raw) > MAX_CANONICAL_ARTIFACT_BYTES:
        raise_vector_index_error(VectorIndexErrorCode.INVALID_ARTIFACT)
    if raw.startswith(codecs.BOM_UTF8) or b"\r" in raw:
        raise_vector_index_error(VectorIndexErrorCode.INVALID_ARTIFACT)
    if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        raise_vector_index_error(VectorIndexErrorCode.INVALID_ARTIFACT)
    try:
        text = raw[:-1].decode("utf-8", errors="strict")
        payload = json.loads(
            text,
            object_pairs_hook=_closed_pairs,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeError, json.JSONDecodeError, _DuplicateKeyError, ValueError, TypeError):
        raise_vector_index_error(VectorIndexErrorCode.INVALID_ARTIFACT)
    if type(payload) is not dict:
        raise_vector_index_error(VectorIndexErrorCode.INVALID_ARTIFACT)
    try:
        artifact = VectorIndexArtifact.model_validate(payload)
    except ValidationError:
        raise_vector_index_error(VectorIndexErrorCode.INVALID_ARTIFACT)
    if canonical_vector_index_bytes(artifact) != raw:
        raise_vector_index_error(VectorIndexErrorCode.INVALID_ARTIFACT)
    return artifact
