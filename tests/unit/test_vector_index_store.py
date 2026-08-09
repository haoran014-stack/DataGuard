from __future__ import annotations

import json
import os
import socket
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import dataguard.vector_index.store as store_module
from dataguard.config import RuntimeSettings
from dataguard.ollama import OllamaHealthFacts, OllamaModelFacts
from dataguard.ollama.client import EMBEDDING_MODEL, GENERATION_MODEL
from dataguard.validation import load_fixture_bundle
from dataguard.vector_index import (
    INDEX_FILENAME,
    MAX_CANONICAL_ARTIFACT_BYTES,
    VECTOR_INDEX_FORMAT,
    StoredIndexErrorCode,
    StoredIndexState,
    VectorIndexArtifact,
    VectorIndexEntry,
    VectorIndexStore,
    VectorIndexStoreError,
    canonical_vector_index_bytes,
    load_canonical_vector_index,
    vector_index_sha256,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_SENTINEL = "STORE_RAW_SENTINEL_SHOULD_NOT_APPEAR"
CORPUS_SHA = "c" * 64
GENERATION_DIGEST = "a" * 64
EMBEDDING_DIGEST = "sha256:" + "b" * 64
DIMENSIONS = 3


@pytest.fixture(scope="module")
def fixture_bundle():
    loaded = load_fixture_bundle(PROJECT_ROOT)
    assert loaded.ok and loaded.bundle is not None
    return loaded.bundle


def _health(*, digest: str = EMBEDDING_DIGEST, dimensions: int = DIMENSIONS):
    return OllamaHealthFacts(
        version="0.12.1",
        generation_model=OllamaModelFacts(tag=GENERATION_MODEL, digest=GENERATION_DIGEST),
        embedding_model=OllamaModelFacts(tag=EMBEDDING_MODEL, digest=digest),
        embedding_dimensions=dimensions,
    )


def _artifact(corpus, *, offset: float = 0.0, corpus_sha: str = CORPUS_SHA):
    ids = tuple(document.doc_id for document in corpus.documents)
    return VectorIndexArtifact(
        format=VECTOR_INDEX_FORMAT,
        corpus_version=corpus.corpus_version,
        corpus_sha256=corpus_sha,
        ordered_document_ids=ids,
        embedding_model_tag=EMBEDDING_MODEL,
        embedding_model_digest=EMBEDDING_DIGEST,
        dimensions=DIMENSIONS,
        entries=tuple(
            VectorIndexEntry(
                doc_id=doc_id,
                vector=(1.0 + offset, float(position + 1), -1.0),
            )
            for position, doc_id in enumerate(ids)
        ),
    )


def _target(root: Path, settings: RuntimeSettings | None = None) -> Path:
    configured = settings or RuntimeSettings()
    return root / configured.runtime_state_dir / INDEX_FILENAME


def _assert_store_error(
    error: VectorIndexStoreError,
    code: StoredIndexErrorCode,
) -> None:
    expected_state = {
        StoredIndexErrorCode.MISSING: StoredIndexState.MISSING,
        StoredIndexErrorCode.CORRUPT: StoredIndexState.CORRUPT,
        StoredIndexErrorCode.STALE: StoredIndexState.STALE,
        StoredIndexErrorCode.IO_ERROR: StoredIndexState.IO_ERROR,
    }[code]
    rendered = " ".join((str(error), repr(error), repr(error.as_dict())))
    assert error.code is code
    assert error.state is expected_state
    assert error.as_dict()["state"] == expected_state.value
    assert set(error.as_dict()) == {"code", "state", "message"}
    assert RAW_SENTINEL not in rendered
    assert "vector-index.v1.json" not in rendered
    assert "artifacts" not in rendered
    assert "[1.0" not in rendered


def test_constructor_only_reads_root_and_prepare_is_explicit(tmp_path: Path, monkeypatch) -> None:
    before = tuple(tmp_path.iterdir())
    writes = 0
    original_mkdir = store_module._create_directory

    def observed_mkdir(path: Path) -> None:
        nonlocal writes
        writes += 1
        original_mkdir(path)

    monkeypatch.setattr(store_module, "_create_directory", observed_mkdir)
    store = VectorIndexStore(tmp_path, RuntimeSettings())
    assert tuple(tmp_path.iterdir()) == before
    assert writes == 0
    assert repr(store) == "VectorIndexStore()"

    store.prepare()
    assert writes == 2
    assert _target(tmp_path).parent.is_dir()
    assert not _target(tmp_path).exists()


def test_valid_prepare_write_read_load_and_overwrite(tmp_path: Path, fixture_bundle) -> None:
    store = VectorIndexStore(tmp_path, RuntimeSettings())
    first = _artifact(fixture_bundle.corpus)
    first_raw = canonical_vector_index_bytes(first)
    facts = store.write(first)

    assert store.read() == first_raw
    assert _target(tmp_path).read_bytes() == first_raw
    assert facts.model_dump() == {
        "artifact_sha256": vector_index_sha256(first_raw),
        "format": VECTOR_INDEX_FORMAT,
        "document_count": 30,
        "dimensions": DIMENSIONS,
    }
    loaded = store.load_validated(fixture_bundle.corpus, CORPUS_SHA, _health())
    assert loaded.facts == facts
    assert loaded.validated_index.document_count == 30
    assert RAW_SENTINEL not in repr(loaded)
    assert str(tmp_path) not in repr(loaded) + repr(facts)

    second = _artifact(fixture_bundle.corpus, offset=0.25)
    second_raw = canonical_vector_index_bytes(second)
    second_facts = store.write(second)
    assert store.read() == second_raw != first_raw
    assert second_facts.artifact_sha256 == vector_index_sha256(second_raw)
    assert not tuple(_target(tmp_path).parent.glob(".*.tmp"))


def test_target_permission_is_owner_only_where_supported(tmp_path: Path, fixture_bundle) -> None:
    store = VectorIndexStore(tmp_path, RuntimeSettings())
    store.write(_artifact(fixture_bundle.corpus))
    mode = stat.S_IMODE(os.lstat(_target(tmp_path)).st_mode)
    if os.name != "nt":
        assert mode == 0o600
    else:
        assert stat.S_ISREG(os.lstat(_target(tmp_path)).st_mode)


def test_write_explicitly_replaces_invalid_regular_target(tmp_path: Path, fixture_bundle) -> None:
    store = VectorIndexStore(tmp_path, RuntimeSettings())
    store.prepare()
    _target(tmp_path).write_bytes((RAW_SENTINEL + "\n").encode())
    artifact = _artifact(fixture_bundle.corpus)
    store.write(artifact)
    assert store.read() == canonical_vector_index_bytes(artifact)


def test_missing_corrupt_stale_and_io_states_are_mutually_exclusive(
    tmp_path: Path,
    fixture_bundle,
) -> None:
    store = VectorIndexStore(tmp_path, RuntimeSettings())
    with pytest.raises(VectorIndexStoreError) as missing:
        store.load_validated(fixture_bundle.corpus, CORPUS_SHA, _health())
    _assert_store_error(missing.value, StoredIndexErrorCode.MISSING)

    store.prepare()
    _target(tmp_path).write_bytes((RAW_SENTINEL + "\n").encode())
    with pytest.raises(VectorIndexStoreError) as corrupt:
        store.load_validated(fixture_bundle.corpus, CORPUS_SHA, _health())
    _assert_store_error(corrupt.value, StoredIndexErrorCode.CORRUPT)

    stale_artifact = _artifact(fixture_bundle.corpus, corpus_sha="d" * 64)
    store.write(stale_artifact)
    with pytest.raises(VectorIndexStoreError) as stale:
        store.load_validated(fixture_bundle.corpus, CORPUS_SHA, _health())
    _assert_store_error(stale.value, StoredIndexErrorCode.STALE)

    _target(tmp_path).unlink()
    _target(tmp_path).mkdir()
    with pytest.raises(VectorIndexStoreError) as io_error:
        store.load_validated(fixture_bundle.corpus, CORPUS_SHA, _health())
    _assert_store_error(io_error.value, StoredIndexErrorCode.IO_ERROR)

    assert {item.value for item in StoredIndexState} == {
        "missing",
        "corrupt",
        "stale",
        "io_error",
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: b"\xef\xbb\xbf" + raw,
        lambda raw: raw.replace(b"\n", b"\r\n"),
        lambda raw: b'{"x":1,"x":2}\n',
    ],
)
def test_canonical_byte_drift_is_corrupt(tmp_path: Path, fixture_bundle, mutate) -> None:
    store = VectorIndexStore(tmp_path, RuntimeSettings())
    store.prepare()
    raw = canonical_vector_index_bytes(_artifact(fixture_bundle.corpus))
    _target(tmp_path).write_bytes(mutate(raw))
    with pytest.raises(VectorIndexStoreError) as captured:
        store.load_validated(fixture_bundle.corpus, CORPUS_SHA, _health())
    _assert_store_error(captured.value, StoredIndexErrorCode.CORRUPT)


def test_size_precheck_rejects_oversize_before_open(tmp_path: Path, monkeypatch) -> None:
    store = VectorIndexStore(tmp_path, RuntimeSettings())
    store.prepare()
    _target(tmp_path).write_bytes(b"x" * 65)
    monkeypatch.setattr(store_module, "MAX_CANONICAL_ARTIFACT_BYTES", 64)
    opened = False

    def forbidden_open(path: Path) -> int:
        nonlocal opened
        opened = True
        raise AssertionError

    monkeypatch.setattr(store_module, "_open_read", forbidden_open)
    with pytest.raises(VectorIndexStoreError) as captured:
        store.read()
    _assert_store_error(captured.value, StoredIndexErrorCode.CORRUPT)
    assert opened is False


def test_short_read_and_growth_are_io_errors(tmp_path: Path, fixture_bundle, monkeypatch) -> None:
    store = VectorIndexStore(tmp_path, RuntimeSettings())
    store.write(_artifact(fixture_bundle.corpus))
    original_read = store_module._read_chunk

    state = {"calls": 0}

    def short_read(fd: int, count: int) -> bytes:
        state["calls"] += 1
        if state["calls"] == 1:
            return original_read(fd, min(count, 10))
        return b""

    monkeypatch.setattr(store_module, "_read_chunk", short_read)
    with pytest.raises(VectorIndexStoreError) as short:
        store.read()
    _assert_store_error(short.value, StoredIndexErrorCode.IO_ERROR)

    monkeypatch.setattr(store_module, "_read_chunk", original_read)
    state["calls"] = 0

    def growth(fd: int, count: int) -> bytes:
        state["calls"] += 1
        if state["calls"] == 1:
            return original_read(fd, count)
        if state["calls"] == 2:
            return b"x"
        return b""

    monkeypatch.setattr(store_module, "_read_chunk", growth)
    with pytest.raises(VectorIndexStoreError) as grown:
        store.read()
    _assert_store_error(grown.value, StoredIndexErrorCode.IO_ERROR)


def test_open_after_identity_change_is_io_error(tmp_path: Path, fixture_bundle, monkeypatch) -> None:
    store = VectorIndexStore(tmp_path, RuntimeSettings())
    store.write(_artifact(fixture_bundle.corpus))
    monkeypatch.setattr(store_module, "_same_identity", lambda left, right: False)
    with pytest.raises(VectorIndexStoreError) as captured:
        store.read()
    _assert_store_error(captured.value, StoredIndexErrorCode.IO_ERROR)


@pytest.mark.parametrize("invalid_root", ["relative", Path("relative")])
def test_constructor_rejects_nonabsolute_root(invalid_root: Any) -> None:
    with pytest.raises(VectorIndexStoreError) as captured:
        VectorIndexStore(invalid_root, RuntimeSettings())  # type: ignore[arg-type]
    _assert_store_error(captured.value, StoredIndexErrorCode.IO_ERROR)


def test_constructor_rejects_root_file_and_deterministic_reparse(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root_file = tmp_path / "root-file"
    root_file.write_text("synthetic", encoding="utf-8")
    with pytest.raises(VectorIndexStoreError) as file_error:
        VectorIndexStore(root_file, RuntimeSettings())
    _assert_store_error(file_error.value, StoredIndexErrorCode.IO_ERROR)

    monkeypatch.setattr(store_module, "_is_reparse", lambda metadata: True)
    with pytest.raises(VectorIndexStoreError) as reparse_error:
        VectorIndexStore(tmp_path, RuntimeSettings())
    _assert_store_error(reparse_error.value, StoredIndexErrorCode.IO_ERROR)


def test_reparse_helper_covers_windows_attribute_and_posix_symlink() -> None:
    windows = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
    posix = SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)
    regular = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0)
    assert store_module._is_reparse(windows)
    assert store_module._is_reparse(posix)
    assert not store_module._is_reparse(regular)


def test_runtime_component_target_reparse_file_and_escape_are_rejected(
    tmp_path: Path,
    fixture_bundle,
    monkeypatch,
) -> None:
    runtime_file_root = tmp_path / "runtime-file-root"
    runtime_file_root.mkdir()
    (runtime_file_root / "artifacts").write_text("synthetic", encoding="utf-8")
    with pytest.raises(VectorIndexStoreError) as runtime_file:
        VectorIndexStore(runtime_file_root, RuntimeSettings()).prepare()
    _assert_store_error(runtime_file.value, StoredIndexErrorCode.IO_ERROR)

    escaped = RuntimeSettings().model_copy(
        update={"runtime_state_dir": Path("artifacts/../escape")}
    )
    with pytest.raises(VectorIndexStoreError) as escape:
        VectorIndexStore(tmp_path, escaped)
    _assert_store_error(escape.value, StoredIndexErrorCode.IO_ERROR)

    normal_root = tmp_path / "target-root"
    normal_root.mkdir()
    store = VectorIndexStore(normal_root, RuntimeSettings())
    store.prepare()
    _target(normal_root).mkdir()
    with pytest.raises(VectorIndexStoreError) as target_directory:
        store.write(_artifact(fixture_bundle.corpus))
    _assert_store_error(target_directory.value, StoredIndexErrorCode.IO_ERROR)

    reparse_root = tmp_path / "reparse-root"
    reparse_root.mkdir()
    reparse_store = VectorIndexStore(reparse_root, RuntimeSettings())
    original_validate = store_module._validate_directory

    def reject_runtime(path: Path):
        if path.name == "runtime":
            store_module._raise_store_error(StoredIndexErrorCode.IO_ERROR)
        return original_validate(path)

    monkeypatch.setattr(store_module, "_validate_directory", reject_runtime)
    with pytest.raises(VectorIndexStoreError) as runtime_reparse:
        reparse_store.prepare()
    _assert_store_error(runtime_reparse.value, StoredIndexErrorCode.IO_ERROR)


def test_target_reparse_branch_and_store_path_length_are_rejected(
    tmp_path: Path,
    fixture_bundle,
    monkeypatch,
) -> None:
    store = VectorIndexStore(tmp_path, RuntimeSettings())
    store.write(_artifact(fixture_bundle.corpus))
    original_regular = store_module._validate_regular

    def reject_target(path: Path):
        if path.name == INDEX_FILENAME:
            store_module._raise_store_error(StoredIndexErrorCode.IO_ERROR)
        return original_regular(path)

    monkeypatch.setattr(store_module, "_validate_regular", reject_target)
    with pytest.raises(VectorIndexStoreError) as target_reparse:
        store.read()
    _assert_store_error(target_reparse.value, StoredIndexErrorCode.IO_ERROR)

    monkeypatch.setattr(store_module, "_validate_regular", original_regular)
    monkeypatch.setattr(store_module, "MAX_STORE_PATH_CHARS", 1)
    with pytest.raises(VectorIndexStoreError) as too_long:
        VectorIndexStore(tmp_path, RuntimeSettings())
    _assert_store_error(too_long.value, StoredIndexErrorCode.IO_ERROR)


def _raise_os_error(*args: Any, **kwargs: Any) -> None:
    raise OSError(RAW_SENTINEL)


@pytest.mark.parametrize(
    "fault_point",
    [
        "exclusive_temp_open",
        "write",
        "flush",
        "fsync",
        "close",
        "temp_revalidate",
        "pre_replace",
        "replace",
    ],
)
def test_precommit_write_fault_preserves_old_bytes_and_cleans_temp(
    tmp_path: Path,
    fixture_bundle,
    monkeypatch,
    fault_point: str,
) -> None:
    root = tmp_path / fault_point
    root.mkdir()
    store = VectorIndexStore(root, RuntimeSettings())
    old = _artifact(fixture_bundle.corpus)
    new = _artifact(fixture_bundle.corpus, offset=0.5)
    store.write(old)
    old_raw = _target(root).read_bytes()

    if fault_point == "exclusive_temp_open":
        monkeypatch.setattr(store_module, "_create_exclusive_temp", _raise_os_error)
    elif fault_point == "write":
        monkeypatch.setattr(store_module, "_write_all", _raise_os_error)
    elif fault_point == "flush":
        monkeypatch.setattr(store_module, "_flush_stream", _raise_os_error)
    elif fault_point == "fsync":
        monkeypatch.setattr(store_module, "_fsync_stream", _raise_os_error)
    elif fault_point == "close":
        original_close = store_module._close_stream

        def close_then_fail(stream) -> None:
            original_close(stream)
            raise OSError(RAW_SENTINEL)

        monkeypatch.setattr(store_module, "_close_stream", close_then_fail)
    elif fault_point == "temp_revalidate":
        original_owned = VectorIndexStore._owned_temp_metadata
        calls = {"count": 0}

        def fail_once(self, path, expected):
            calls["count"] += 1
            if calls["count"] == 1:
                raise VectorIndexStoreError(StoredIndexErrorCode.IO_ERROR)
            return original_owned(self, path, expected)

        monkeypatch.setattr(VectorIndexStore, "_owned_temp_metadata", fail_once)
    elif fault_point == "pre_replace":
        monkeypatch.setattr(VectorIndexStore, "_pre_replace_validate", _raise_os_error)
    else:
        monkeypatch.setattr(store_module, "_replace_path", _raise_os_error)

    with pytest.raises(VectorIndexStoreError) as captured:
        store.write(new)
    _assert_store_error(captured.value, StoredIndexErrorCode.IO_ERROR)
    assert _target(root).read_bytes() == old_raw
    assert not tuple(_target(root).parent.glob(".*.tmp"))


def test_postcommit_check_failure_is_exact_new_or_old_and_never_partial(
    tmp_path: Path,
    fixture_bundle,
    monkeypatch,
) -> None:
    store = VectorIndexStore(tmp_path, RuntimeSettings())
    old = _artifact(fixture_bundle.corpus)
    new = _artifact(fixture_bundle.corpus, offset=0.75)
    store.write(old)
    old_raw = canonical_vector_index_bytes(old)
    new_raw = canonical_vector_index_bytes(new)
    monkeypatch.setattr(VectorIndexStore, "_post_replace_validate", _raise_os_error)
    with pytest.raises(VectorIndexStoreError) as captured:
        store.write(new)
    _assert_store_error(captured.value, StoredIndexErrorCode.IO_ERROR)
    actual = _target(tmp_path).read_bytes()
    assert actual in {old_raw, new_raw}
    assert actual == new_raw
    assert not tuple(_target(tmp_path).parent.glob(".*.tmp"))


def test_fdopen_failure_closes_raw_fd_cleans_owned_temp_and_preserves_old(
    tmp_path: Path,
    fixture_bundle,
    monkeypatch,
) -> None:
    store = VectorIndexStore(tmp_path, RuntimeSettings())
    old = _artifact(fixture_bundle.corpus)
    store.write(old)
    old_raw = _target(tmp_path).read_bytes()
    unrelated = _target(tmp_path).parent / "unrelated.keep"
    unrelated.write_text("keep", encoding="utf-8")
    captured_fd = {"value": -1}

    def fail_fdopen(fd: int):
        captured_fd["value"] = fd
        raise OSError(RAW_SENTINEL)

    monkeypatch.setattr(store_module, "_fdopen_write", fail_fdopen)
    with pytest.raises(VectorIndexStoreError) as captured:
        store.write(_artifact(fixture_bundle.corpus, offset=0.875))
    _assert_store_error(captured.value, StoredIndexErrorCode.IO_ERROR)
    with pytest.raises(OSError):
        os.fstat(captured_fd["value"])
    assert _target(tmp_path).read_bytes() == old_raw
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert not tuple(_target(tmp_path).parent.glob(".vector-index.write.*.tmp"))


def test_post_create_fstat_failure_closes_fd_without_untrusted_path_delete(
    tmp_path: Path,
    fixture_bundle,
    monkeypatch,
) -> None:
    store = VectorIndexStore(tmp_path, RuntimeSettings())
    old = _artifact(fixture_bundle.corpus)
    store.write(old)
    old_raw = _target(tmp_path).read_bytes()
    unrelated = _target(tmp_path).parent / "unrelated.keep"
    unrelated.write_text("keep", encoding="utf-8")
    captured_fd = {"value": -1}
    original_create = store_module._create_exclusive_temp

    def capture_create(parent: Path, purpose: str):
        fd, path = original_create(parent, purpose)
        captured_fd["value"] = fd
        return fd, path

    monkeypatch.setattr(store_module, "_create_exclusive_temp", capture_create)
    monkeypatch.setattr(store_module, "_fstat_fd", _raise_os_error)
    with pytest.raises(VectorIndexStoreError) as captured:
        store.write(_artifact(fixture_bundle.corpus, offset=0.9375))
    _assert_store_error(captured.value, StoredIndexErrorCode.IO_ERROR)
    with pytest.raises(OSError):
        os.fstat(captured_fd["value"])
    assert _target(tmp_path).read_bytes() == old_raw
    assert unrelated.read_text(encoding="utf-8") == "keep"
    residuals = tuple(_target(tmp_path).parent.glob(".vector-index.write.*.tmp"))
    assert len(residuals) == 1
    assert residuals[0].is_file()


def test_cleanup_failure_is_fixed_io_and_never_deletes_unrelated_file(
    tmp_path: Path,
    fixture_bundle,
    monkeypatch,
) -> None:
    store = VectorIndexStore(tmp_path, RuntimeSettings())
    old = _artifact(fixture_bundle.corpus)
    store.write(old)
    old_raw = _target(tmp_path).read_bytes()
    unrelated = _target(tmp_path).parent / "unrelated.keep"
    unrelated.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(store_module, "_write_all", _raise_os_error)
    monkeypatch.setattr(store_module, "_unlink_path", _raise_os_error)
    with pytest.raises(VectorIndexStoreError) as captured:
        store.write(_artifact(fixture_bundle.corpus, offset=1.0))
    _assert_store_error(captured.value, StoredIndexErrorCode.IO_ERROR)
    assert _target(tmp_path).read_bytes() == old_raw
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert len(tuple(_target(tmp_path).parent.glob(".vector-index.write.*.tmp"))) == 1


def test_same_instance_concurrent_reads_and_writes_never_observe_partial(
    tmp_path: Path,
    fixture_bundle,
) -> None:
    store = VectorIndexStore(tmp_path, RuntimeSettings())
    artifacts = tuple(
        _artifact(fixture_bundle.corpus, offset=position / 10)
        for position in range(4)
    )
    expected = {canonical_vector_index_bytes(artifact) for artifact in artifacts}
    store.write(artifacts[0])

    def write_one(artifact: VectorIndexArtifact) -> bytes:
        store.write(artifact)
        return store.read()

    def read_one(_: int) -> bytes:
        raw = store.read()
        load_canonical_vector_index(raw)
        return raw

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(write_one, artifact) for artifact in artifacts]
        futures += [executor.submit(read_one, position) for position in range(12)]
        observed = [future.result(timeout=10) for future in futures]
    assert all(raw in expected for raw in observed)
    assert not tuple(_target(tmp_path).parent.glob(".*.tmp"))


def test_store_never_calls_network_ollama_or_database(
    tmp_path: Path,
    fixture_bundle,
    monkeypatch,
) -> None:
    import sqlite3
    from dataguard.ollama import OllamaClient

    monkeypatch.setattr(socket, "create_connection", _raise_os_error)
    monkeypatch.setattr(sqlite3, "connect", _raise_os_error)
    monkeypatch.setattr(OllamaClient, "embed", _raise_os_error)
    store = VectorIndexStore(tmp_path, RuntimeSettings())
    artifact = _artifact(fixture_bundle.corpus)
    store.write(artifact)
    assert store.load_validated(
        fixture_bundle.corpus,
        CORPUS_SHA,
        _health(),
    ).facts.document_count == 30


def test_import_performs_no_filesystem_or_network_io() -> None:
    script = r'''
import os
import pathlib
import socket
import pydantic
import dataguard.domain
import dataguard.ollama
import dataguard.config

def forbidden(*args, **kwargs):
    raise RuntimeError("side effect")

os.open = forbidden
os.lstat = forbidden
os.mkdir = forbidden
os.replace = forbidden
pathlib.Path.read_bytes = forbidden
pathlib.Path.read_text = forbidden
socket.create_connection = forbidden
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
