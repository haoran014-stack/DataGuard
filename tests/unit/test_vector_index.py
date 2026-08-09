from __future__ import annotations

import asyncio
import codecs
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from dataguard.config import RuntimeSettings
from dataguard.ollama import OllamaClient, OllamaHealthFacts, OllamaModelFacts
from dataguard.ollama.client import EMBEDDING_MODEL, GENERATION_MODEL
from dataguard.ollama.client import MAX_EMBED_INPUTS, MAX_EMBED_TOTAL_CHARS
from dataguard.validation import load_fixture_bundle
from dataguard.vector_index import (
    MAX_CANONICAL_ARTIFACT_BYTES,
    MAX_VECTOR_DIMENSIONS,
    VECTOR_INDEX_FORMAT,
    ValidatedVectorIndex,
    VectorIndexArtifact,
    VectorIndexEntry,
    VectorIndexError,
    VectorIndexErrorCode,
    build_vector_index,
    canonical_vector_index_bytes,
    document_embedding_input,
    load_canonical_vector_index,
    retrieve,
    validate_vector_index_binding,
    vector_index_sha256,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_SENTINEL = "INDEX_RAW_SENTINEL_SHOULD_NOT_APPEAR"
CORPUS_SHA = "c" * 64
GENERATION_DIGEST = "a" * 64
EMBEDDING_DIGEST = "sha256:" + "b" * 64
DIMENSIONS = 3


def _run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


@pytest.fixture(scope="module")
def fixture_bundle():
    loaded = load_fixture_bundle(PROJECT_ROOT)
    assert loaded.ok
    assert loaded.bundle is not None
    return loaded.bundle


def _health(*, dimensions: int = DIMENSIONS, digest: str = EMBEDDING_DIGEST) -> OllamaHealthFacts:
    return OllamaHealthFacts(
        version="0.12.1",
        generation_model=OllamaModelFacts(tag=GENERATION_MODEL, digest=GENERATION_DIGEST),
        embedding_model=OllamaModelFacts(tag=EMBEDDING_MODEL, digest=digest),
        embedding_dimensions=dimensions,
    )


def _artifact(corpus, *, dimensions: int = DIMENSIONS) -> VectorIndexArtifact:
    ids = tuple(document.doc_id for document in corpus.documents)
    entries = tuple(
        VectorIndexEntry(
            doc_id=doc_id,
            vector=(1.0, float(position + 1), -1.0)[:dimensions],
        )
        for position, doc_id in enumerate(ids)
    )
    return VectorIndexArtifact(
        format=VECTOR_INDEX_FORMAT,
        corpus_version=corpus.corpus_version,
        corpus_sha256=CORPUS_SHA,
        ordered_document_ids=ids,
        embedding_model_tag=EMBEDDING_MODEL,
        embedding_model_digest=EMBEDDING_DIGEST,
        dimensions=dimensions,
        entries=entries,
    )


def _assert_safe_error(error: VectorIndexError) -> None:
    rendered = " ".join((str(error), repr(error), repr(error.as_dict())))
    assert set(error.as_dict()) == {"code", "message"}
    assert RAW_SENTINEL not in rendered
    assert "[1.0" not in rendered
    assert "http://" not in rendered


def test_build_uses_exact_document_inputs_order_and_real_adapter_surface(fixture_bundle) -> None:
    requests: list[httpx.Request] = []
    documents = fixture_bundle.corpus.documents

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        inputs = json.loads(request.content)["input"]
        return httpx.Response(
            200,
            json={
                "model": EMBEDDING_MODEL,
                "embeddings": [
                    [1.0, float(position), -1.0]
                    for position, _ in enumerate(inputs, start=1)
                ],
            },
            headers={"Content-Type": "application/json"},
        )

    async def exercise() -> VectorIndexArtifact:
        async with OllamaClient(
            RuntimeSettings(),
            transport=httpx.MockTransport(handler),
        ) as client:
            return await build_vector_index(
                fixture_bundle.corpus,
                fixture_bundle.corpus_sha256,
                _health(),
                client,
            )

    artifact = _run(exercise())
    assert len(requests) == 1
    assert len(documents) == 30 < MAX_EMBED_INPUTS
    assert sum(len(document_embedding_input(document)) for document in documents) < MAX_EMBED_TOTAL_CHARS
    assert artifact.ordered_document_ids == tuple(document.doc_id for document in documents)
    request = requests[0]
    assert (request.method, request.url.path) == ("POST", "/api/embed")
    assert json.loads(request.content) == {
        "model": EMBEDDING_MODEL,
        "input": [document.title + "\n\n" + document.content for document in documents],
        "truncate": False,
    }
    for document in documents:
        assert document_embedding_input(document) == document.title + "\n\n" + document.content


def test_build_passes_expected_dimensions_and_rejects_zero_vector(fixture_bundle) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        count = len(json.loads(request.content)["input"])
        return httpx.Response(
            200,
            json={
                "model": EMBEDDING_MODEL,
                "embeddings": [[0.0, 0.0, 0.0] for _ in range(count)],
            },
            headers={"Content-Type": "application/json"},
        )

    async def exercise() -> None:
        async with OllamaClient(
            RuntimeSettings(),
            transport=httpx.MockTransport(handler),
        ) as client:
            await build_vector_index(
                fixture_bundle.corpus,
                fixture_bundle.corpus_sha256,
                _health(),
                client,
            )

    with pytest.raises(VectorIndexError) as captured:
        _run(exercise())
    assert captured.value.code is VectorIndexErrorCode.INVALID_INPUT
    _assert_safe_error(captured.value)


def test_canonical_bytes_digest_round_trip_and_replay_are_stable(fixture_bundle) -> None:
    artifact = _artifact(fixture_bundle.corpus)
    raw = canonical_vector_index_bytes(artifact)
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert b"\r" not in raw and not raw.startswith(codecs.BOM_UTF8)
    assert len(raw) <= MAX_CANONICAL_ARTIFACT_BYTES
    assert raw == canonical_vector_index_bytes(load_canonical_vector_index(raw))
    assert vector_index_sha256(raw) == vector_index_sha256(raw)
    assert vector_index_sha256(raw) == __import__("hashlib").sha256(raw).hexdigest()
    first_object_keys = list(json.loads(raw).keys())
    assert first_object_keys == sorted(first_object_keys)


def test_loader_rejects_key_order_drift(fixture_bundle) -> None:
    artifact = _artifact(fixture_bundle.corpus)
    payload = artifact.model_dump(mode="json")
    reversed_payload = dict(reversed(tuple(payload.items())))
    raw = json.dumps(
        reversed_payload,
        ensure_ascii=False,
        sort_keys=False,
        separators=(",", ":"),
    ).encode() + b"\n"
    with pytest.raises(VectorIndexError):
        load_canonical_vector_index(raw)


def test_artifact_contains_only_ids_vectors_and_bindings_not_corpus_literals(fixture_bundle) -> None:
    raw = canonical_vector_index_bytes(_artifact(fixture_bundle.corpus))
    text = raw.decode("utf-8")
    for document in fixture_bundle.corpus.documents:
        assert document.title not in text
        assert document.content not in text
        for canary in document.canaries:
            assert canary.value not in text
        for fragment in document.protected_fragments:
            assert fragment.value not in text
    assert set(json.loads(raw)) == {
        "corpus_sha256",
        "corpus_version",
        "dimensions",
        "embedding_model_digest",
        "embedding_model_tag",
        "entries",
        "format",
        "ordered_document_ids",
    }
    assert set(json.loads(raw)["entries"][0]) == {"doc_id", "vector"}
    rendered = repr(_artifact(fixture_bundle.corpus))
    assert fixture_bundle.corpus.documents[0].doc_id not in rendered
    assert "vector=" not in rendered


def _mutated_raw(artifact: VectorIndexArtifact, mutate) -> bytes:
    payload = artifact.model_dump(mode="json")
    mutate(payload)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8") + b"\n"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda raw: codecs.BOM_UTF8 + raw,
        lambda raw: raw.replace(b"\n", b"\r\n"),
        lambda raw: raw[:-1],
        lambda raw: raw + b"\n",
        lambda raw: b" " + raw,
        lambda raw: raw + b" ",
        lambda raw: json.dumps(json.loads(raw), indent=2).encode() + b"\n",
    ],
)
def test_loader_rejects_noncanonical_byte_forms(fixture_bundle, mutation) -> None:
    raw = canonical_vector_index_bytes(_artifact(fixture_bundle.corpus))
    with pytest.raises(VectorIndexError) as captured:
        load_canonical_vector_index(mutation(raw))
    assert captured.value.code is VectorIndexErrorCode.INVALID_ARTIFACT
    _assert_safe_error(captured.value)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}\n',
        b"[]\n",
        b'{"x":NaN}\n',
        b"\xff\n",
        (RAW_SENTINEL + "\n").encode(),
    ],
)
def test_loader_rejects_duplicate_nonobject_nonfinite_utf8_and_raw_text(raw: bytes) -> None:
    with pytest.raises(VectorIndexError) as captured:
        load_canonical_vector_index(raw)
    _assert_safe_error(captured.value)


def test_digest_rejects_noncanonical_bytes(fixture_bundle) -> None:
    raw = canonical_vector_index_bytes(_artifact(fixture_bundle.corpus))
    with pytest.raises(VectorIndexError):
        vector_index_sha256(raw[:-1])


def test_loader_rejects_unknown_top_level_and_entry_raw_fields(fixture_bundle) -> None:
    artifact = _artifact(fixture_bundle.corpus)
    for raw in (
        _mutated_raw(artifact, lambda payload: payload.__setitem__("unknown", RAW_SENTINEL)),
        _mutated_raw(
            artifact,
            lambda payload: payload["entries"][0].__setitem__("content", RAW_SENTINEL),
        ),
    ):
        with pytest.raises(VectorIndexError) as captured:
            load_canonical_vector_index(raw)
        _assert_safe_error(captured.value)


def test_loader_enforces_bound_before_decode(monkeypatch) -> None:
    import dataguard.vector_index.canonical as codec

    monkeypatch.setattr(codec, "MAX_CANONICAL_ARTIFACT_BYTES", 8)
    with pytest.raises(VectorIndexError) as captured:
        codec.load_canonical_vector_index((RAW_SENTINEL + "\n").encode())
    _assert_safe_error(captured.value)


@pytest.mark.parametrize(
    "vector",
    [
        (),
        [],
        [0, 0, 0],
        [True, 1, 2],
        [float("nan"), 1, 2],
        [float("inf"), 1, 2],
        [sys.float_info.max, sys.float_info.max, sys.float_info.max],
        [RAW_SENTINEL, 1, 2],
        [1.0] * (MAX_VECTOR_DIMENSIONS + 1),
    ],
)
def test_entry_rejects_empty_bool_nonfinite_zero_and_invalid_norm_without_echo(vector) -> None:
    with pytest.raises(ValidationError) as captured:
        VectorIndexEntry(doc_id="synthetic-doc", vector=vector)
    assert RAW_SENTINEL not in str(captured.value) + repr(captured.value)


def test_artifact_rejects_missing_extra_reordered_duplicate_and_dimension_drift(fixture_bundle) -> None:
    payload = _artifact(fixture_bundle.corpus).model_dump(mode="python")
    mutations = []
    missing = dict(payload)
    missing.pop("format")
    mutations.append(missing)
    extra = dict(payload, unknown=RAW_SENTINEL)
    mutations.append(extra)
    reordered = dict(payload)
    reordered["ordered_document_ids"] = tuple(reversed(payload["ordered_document_ids"]))
    mutations.append(reordered)
    duplicate = dict(payload)
    ids = list(payload["ordered_document_ids"])
    ids[-1] = ids[0]
    duplicate["ordered_document_ids"] = ids
    mutations.append(duplicate)
    wrong_dimension = dict(payload)
    wrong_dimension["dimensions"] = 2
    mutations.append(wrong_dimension)
    missing_entry = dict(payload)
    missing_entry["entries"] = payload["entries"][:-1]
    mutations.append(missing_entry)
    extra_entry = dict(payload)
    extra_entry["entries"] = (*payload["entries"], payload["entries"][0])
    mutations.append(extra_entry)
    for mutation in mutations:
        with pytest.raises(ValidationError) as captured:
            VectorIndexArtifact.model_validate(mutation)
        assert RAW_SENTINEL not in str(captured.value) + repr(captured.value)


@pytest.mark.parametrize("dimensions", [0, MAX_VECTOR_DIMENSIONS + 1, True])
def test_artifact_dimension_bound_is_closed(fixture_bundle, dimensions) -> None:
    payload = _artifact(fixture_bundle.corpus).model_dump(mode="python")
    payload["dimensions"] = dimensions
    with pytest.raises(ValidationError):
        VectorIndexArtifact.model_validate(payload)


def test_binding_returns_opaque_handle_and_direct_construction_is_blocked(fixture_bundle) -> None:
    artifact = _artifact(fixture_bundle.corpus)
    bound = validate_vector_index_binding(
        artifact,
        fixture_bundle.corpus,
        CORPUS_SHA,
        _health(),
    )
    assert bound.document_count == 30 and bound.dimensions == DIMENSIONS
    rendered = repr(bound)
    assert "vector=" not in rendered.lower()
    assert fixture_bundle.corpus.documents[0].doc_id not in rendered
    with pytest.raises((AttributeError, TypeError, ValidationError)):
        bound.dimensions = 2  # type: ignore[misc]
    assert "[1.0" not in rendered
    with pytest.raises(VectorIndexError) as captured:
        ValidatedVectorIndex(artifact, tuple(1.0 for _ in range(30)), _token=object())
    assert captured.value.code is VectorIndexErrorCode.BINDING_MISMATCH

    with pytest.raises(VectorIndexError) as retrieval_error:
        retrieve(artifact, (1.0, 0.0, 0.0), ())  # type: ignore[arg-type]
    assert retrieval_error.value.code is VectorIndexErrorCode.BINDING_MISMATCH


def test_internal_artifact_repr_hides_ordered_ids_entries_and_dynamic_vector(fixture_bundle) -> None:
    dynamic_value = float(len(RAW_SENTINEL) * 1_000_000 + 0.125)
    entry = VectorIndexEntry(doc_id="synthetic-repr-doc", vector=(dynamic_value, 1.0, 2.0))
    artifact = _artifact(fixture_bundle.corpus).model_copy(
        update={"entries": (entry, *_artifact(fixture_bundle.corpus).entries[1:])}
    )
    assert repr(dynamic_value) not in repr(entry)
    assert repr(dynamic_value) not in repr(artifact)
    assert fixture_bundle.corpus.documents[0].doc_id not in repr(artifact)


def test_binding_accepts_unprefixed_local_embedding_digest(fixture_bundle) -> None:
    digest = "b" * 64
    artifact = _artifact(fixture_bundle.corpus).model_copy(
        update={"embedding_model_digest": digest}
    )
    bound = validate_vector_index_binding(
        artifact,
        fixture_bundle.corpus,
        CORPUS_SHA,
        _health(digest=digest),
    )
    assert bound.document_count == 30


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("format", "drift"),
        ("corpus_version", "drift"),
        ("corpus_sha256", "d" * 64),
        ("embedding_model_tag", "drift"),
        ("embedding_model_digest", "d" * 64),
        ("dimensions", 2),
    ],
)
def test_binding_rejects_artifact_field_drift(fixture_bundle, field: str, value: Any) -> None:
    artifact = _artifact(fixture_bundle.corpus).model_copy(update={field: value})
    with pytest.raises(VectorIndexError) as captured:
        validate_vector_index_binding(artifact, fixture_bundle.corpus, CORPUS_SHA, _health())
    assert captured.value.code is VectorIndexErrorCode.BINDING_MISMATCH
    _assert_safe_error(captured.value)


def test_binding_rejects_order_entry_vector_corpus_digest_and_health_drift(fixture_bundle) -> None:
    valid = _artifact(fixture_bundle.corpus)
    artifacts = [
        valid.model_copy(
            update={"ordered_document_ids": tuple(reversed(valid.ordered_document_ids))}
        ),
        valid.model_copy(update={"entries": tuple(reversed(valid.entries))}),
        valid.model_copy(update={"entries": valid.entries[:-1]}),
        valid.model_copy(update={"entries": (*valid.entries, valid.entries[0])}),
        valid.model_copy(
            update={
                "entries": (
                    valid.entries[0].model_copy(update={"vector": (1.0,)}),
                    *valid.entries[1:],
                )
            }
        ),
    ]
    cases = [
        (artifact, CORPUS_SHA, _health()) for artifact in artifacts
    ] + [
        (valid, "d" * 64, _health()),
        (valid, CORPUS_SHA, _health(digest="d" * 64)),
        (valid, CORPUS_SHA, _health(dimensions=2)),
    ]
    for artifact, corpus_sha, health in cases:
        with pytest.raises(VectorIndexError) as captured:
            validate_vector_index_binding(
                artifact,
                fixture_bundle.corpus,
                corpus_sha,
                health,
            )
        _assert_safe_error(captured.value)


def _retrieval_artifact(corpus) -> VectorIndexArtifact:
    ids = tuple(document.doc_id for document in corpus.documents)
    vectors = [(1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.8, 0.2, 0.0), (0.7, 0.3, 0.0)]
    vectors.extend((0.0, 1.0, float(position + 1)) for position in range(26))
    return VectorIndexArtifact(
        format=VECTOR_INDEX_FORMAT,
        corpus_version=corpus.corpus_version,
        corpus_sha256=CORPUS_SHA,
        ordered_document_ids=ids,
        embedding_model_tag=EMBEDDING_MODEL,
        embedding_model_digest=EMBEDDING_DIGEST,
        dimensions=3,
        entries=tuple(
            VectorIndexEntry(doc_id=doc_id, vector=vector)
            for doc_id, vector in zip(ids, vectors, strict=True)
        ),
    )


def test_retrieval_prefilters_before_scoring_top4_tie_and_repeat(fixture_bundle) -> None:
    artifact = _retrieval_artifact(fixture_bundle.corpus)
    bound = validate_vector_index_binding(artifact, fixture_bundle.corpus, CORPUS_SHA, _health())
    ids = artifact.ordered_document_ids
    eligible = (ids[3], ids[1], ids[0], ids[2], ids[10])
    result = retrieve(bound, (1.0, 0.0, 0.0), eligible)
    assert len(result) == 4
    assert tuple(item.doc_id for item in result[:2]) == tuple(sorted((ids[0], ids[1])))
    assert ids[10] not in tuple(item.doc_id for item in result)
    assert result == retrieve(bound, (1.0, 0.0, 0.0), tuple(reversed(eligible)))
    assert all(-1.0 <= item.similarity_score <= 1.0 for item in result)
    assert all(set(item.model_dump()) == {"doc_id", "similarity_score"} for item in result)


def test_retrieval_returns_all_when_fewer_than_four_and_excludes_high_ineligible(fixture_bundle) -> None:
    artifact = _retrieval_artifact(fixture_bundle.corpus)
    bound = validate_vector_index_binding(artifact, fixture_bundle.corpus, CORPUS_SHA, _health())
    ids = artifact.ordered_document_ids
    result = retrieve(bound, (1.0, 0.0, 0.0), (ids[3], ids[10]))
    assert tuple(item.doc_id for item in result) == (ids[3], ids[10])
    assert ids[0] not in {item.doc_id for item in result}
    assert retrieve(bound, (1.0, 0.0, 0.0), ()) == ()


@pytest.mark.parametrize(
    "query",
    [
        [1.0, 0.0, 0.0],
        (),
        (1.0,),
        (0.0, 0.0, 0.0),
        (True, 0.0, 0.0),
        (float("nan"), 0.0, 0.0),
        (float("inf"), 0.0, 0.0),
        (sys.float_info.max, sys.float_info.max, sys.float_info.max),
        (RAW_SENTINEL, 0.0, 0.0),
    ],
)
def test_retrieval_rejects_query_shape_bool_nonfinite_zero_and_invalid_norm(
    fixture_bundle,
    query,
) -> None:
    bound = validate_vector_index_binding(
        _retrieval_artifact(fixture_bundle.corpus),
        fixture_bundle.corpus,
        CORPUS_SHA,
        _health(),
    )
    with pytest.raises(VectorIndexError) as captured:
        retrieve(bound, query, ())
    assert captured.value.code is VectorIndexErrorCode.INVALID_QUERY
    _assert_safe_error(captured.value)


@pytest.mark.parametrize(
    "eligible",
    [
        [],
        ("unknown-document",),
        (RAW_SENTINEL,),
        ("same", "same"),
        (1,),
        tuple(f"unknown-{position}" for position in range(31)),
    ],
)
def test_retrieval_rejects_eligible_shape_unknown_and_duplicates(fixture_bundle, eligible) -> None:
    bound = validate_vector_index_binding(
        _retrieval_artifact(fixture_bundle.corpus),
        fixture_bundle.corpus,
        CORPUS_SHA,
        _health(),
    )
    with pytest.raises(VectorIndexError) as captured:
        retrieve(bound, (1.0, 0.0, 0.0), eligible)
    _assert_safe_error(captured.value)


def test_import_performs_no_network_resource_or_fixture_io() -> None:
    script = r'''
import pathlib
import socket
import httpx
import pydantic
import dataguard.domain
import dataguard.ollama

def forbidden(*args, **kwargs):
    raise RuntimeError("side effect")

pathlib.Path.read_bytes = forbidden
pathlib.Path.read_text = forbidden
socket.create_connection = forbidden
httpx.AsyncClient = forbidden
import dataguard.vector_index
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
