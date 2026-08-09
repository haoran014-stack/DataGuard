"""Safe local filesystem store for the canonical v1 vector index.

The store performs no filesystem mutation at import or construction time.
Directory creation, reads, and writes are explicit and serialized per instance.
"""

from __future__ import annotations

import os
import secrets
import stat
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import BinaryIO, NoReturn

from pydantic import BaseModel, ConfigDict, Field

from dataguard.config import RuntimeSettings
from dataguard.domain import Corpus
from dataguard.ollama import OllamaHealthFacts
from dataguard.vector_index.canonical import (
    canonical_vector_index_bytes,
    load_canonical_vector_index,
    vector_index_sha256,
)
from dataguard.vector_index.core import ValidatedVectorIndex, validate_vector_index_binding
from dataguard.vector_index.errors import VectorIndexError
from dataguard.vector_index.models import (
    DOCUMENT_COUNT,
    MAX_CANONICAL_ARTIFACT_BYTES,
    MAX_VECTOR_DIMENSIONS,
    VECTOR_INDEX_FORMAT,
    VectorIndexArtifact,
)


INDEX_FILENAME = "vector-index.v1.json"
MAX_STORE_PATH_CHARS = 1_024
_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_BINARY_FLAG = getattr(os, "O_BINARY", 0)
_NOFOLLOW_FLAG = getattr(os, "O_NOFOLLOW", 0)


class StoredIndexState(str, Enum):
    MISSING = "missing"
    CORRUPT = "corrupt"
    STALE = "stale"
    IO_ERROR = "io_error"


class StoredIndexErrorCode(str, Enum):
    MISSING = "vector_index_missing"
    CORRUPT = "vector_index_corrupt"
    STALE = "vector_index_stale"
    IO_ERROR = "vector_index_io_error"


_ERROR_STATE = {
    StoredIndexErrorCode.MISSING: StoredIndexState.MISSING,
    StoredIndexErrorCode.CORRUPT: StoredIndexState.CORRUPT,
    StoredIndexErrorCode.STALE: StoredIndexState.STALE,
    StoredIndexErrorCode.IO_ERROR: StoredIndexState.IO_ERROR,
}
_SAFE_MESSAGES = {
    StoredIndexErrorCode.MISSING: "The local vector index is missing.",
    StoredIndexErrorCode.CORRUPT: "The local vector index is corrupt.",
    StoredIndexErrorCode.STALE: "The local vector index binding is stale.",
    StoredIndexErrorCode.IO_ERROR: "The local vector index could not be accessed safely.",
}


class VectorIndexStoreError(Exception):
    """Content-free store failure with one mutually exclusive state."""

    __slots__ = ("code", "state", "message")

    def __init__(self, code: StoredIndexErrorCode) -> None:
        if not isinstance(code, StoredIndexErrorCode):
            raise TypeError("Stored vector index error code is invalid")
        self.code = code
        self.state = _ERROR_STATE[code]
        self.message = _SAFE_MESSAGES[code]
        super().__init__(self.message)

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code.value,
            "state": self.state.value,
            "message": self.message,
        }


def _raise_store_error(code: StoredIndexErrorCode) -> NoReturn:
    raise VectorIndexStoreError(code) from None


class StoredIndexFacts(BaseModel):
    """Minimized facts safe for an internal readiness surface."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )

    artifact_sha256: str = Field(strict=True, pattern=r"^[a-f0-9]{64}$")
    format: str = Field(strict=True, pattern=r"^dataguard-vector-index-v1$")
    document_count: int = Field(strict=True, ge=DOCUMENT_COUNT, le=DOCUMENT_COUNT)
    dimensions: int = Field(strict=True, ge=1, le=MAX_VECTOR_DIMENSIONS)


@dataclass(frozen=True, slots=True, repr=False)
class LoadedVectorIndex:
    validated_index: ValidatedVectorIndex
    facts: StoredIndexFacts

    def __repr__(self) -> str:
        return (
            "LoadedVectorIndex("
            f"format={self.facts.format!r}, documents={self.facts.document_count}, "
            f"dimensions={self.facts.dimensions})"
        )


def _is_reparse(metadata: os.stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE
    )


def _identity(metadata: os.stat_result) -> tuple[int, int]:
    return (metadata.st_dev, metadata.st_ino)


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return _identity(left) == _identity(right)


def _lstat(path: Path) -> os.stat_result:
    return os.lstat(path)


def _validate_directory(path: Path) -> os.stat_result:
    metadata = _lstat(path)
    if _is_reparse(metadata) or not stat.S_ISDIR(metadata.st_mode):
        _raise_store_error(StoredIndexErrorCode.IO_ERROR)
    return metadata


def _validate_regular(path: Path) -> os.stat_result:
    metadata = _lstat(path)
    if _is_reparse(metadata) or not stat.S_ISREG(metadata.st_mode):
        _raise_store_error(StoredIndexErrorCode.IO_ERROR)
    return metadata


def _create_directory(path: Path) -> None:
    os.mkdir(path, mode=0o700)


def _open_read(path: Path) -> int:
    return os.open(path, os.O_RDONLY | _BINARY_FLAG | _NOFOLLOW_FLAG)


def _read_chunk(fd: int, count: int) -> bytes:
    return os.read(fd, count)


def _close_fd(fd: int) -> None:
    os.close(fd)


def _fstat_fd(fd: int) -> os.stat_result:
    return os.fstat(fd)


def _create_exclusive_temp(parent: Path, purpose: str) -> tuple[int, Path]:
    for _ in range(8):
        candidate = parent / f".{purpose}.{secrets.token_hex(16)}.tmp"
        try:
            fd = os.open(
                candidate,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | _BINARY_FLAG | _NOFOLLOW_FLAG,
                0o600,
            )
        except FileExistsError:
            continue
        return fd, candidate
    _raise_store_error(StoredIndexErrorCode.IO_ERROR)


def _fdopen_write(fd: int) -> BinaryIO:
    return os.fdopen(fd, "wb", buffering=0, closefd=True)


def _write_all(stream: BinaryIO, raw: bytes) -> None:
    offset = 0
    while offset < len(raw):
        written = stream.write(raw[offset:])
        if type(written) is not int or written <= 0:
            raise OSError
        offset += written


def _flush_stream(stream: BinaryIO) -> None:
    stream.flush()


def _fsync_stream(stream: BinaryIO) -> None:
    os.fsync(stream.fileno())


def _close_stream(stream: BinaryIO) -> None:
    stream.close()


def _replace_path(source: Path, target: Path) -> None:
    os.replace(source, target)


def _unlink_path(path: Path) -> None:
    os.unlink(path)


class VectorIndexStore:
    """Explicit, path-minimizing canonical index filesystem boundary."""

    __slots__ = ("_project_root", "_runtime_parts", "_runtime_dir", "_target", "_lock")

    def __init__(self, project_root: Path, settings: RuntimeSettings) -> None:
        if not isinstance(project_root, Path) or not project_root.is_absolute():
            _raise_store_error(StoredIndexErrorCode.IO_ERROR)
        if not isinstance(settings, RuntimeSettings):
            _raise_store_error(StoredIndexErrorCode.IO_ERROR)

        lexical_root = Path(os.path.abspath(os.fspath(project_root)))
        try:
            root_metadata = _validate_directory(lexical_root)
            resolved_root = lexical_root.resolve(strict=True)
        except VectorIndexStoreError:
            raise
        except (OSError, RuntimeError):
            _raise_store_error(StoredIndexErrorCode.IO_ERROR)
        if _is_reparse(root_metadata) or os.path.normcase(str(resolved_root)) != os.path.normcase(
            str(lexical_root)
        ):
            _raise_store_error(StoredIndexErrorCode.IO_ERROR)

        runtime = settings.runtime_state_dir
        if (
            not isinstance(runtime, Path)
            or runtime.is_absolute()
            or bool(runtime.drive)
            or not runtime.parts
            or runtime.parts[0] != "artifacts"
            or any(part in {"", ".", ".."} for part in runtime.parts)
        ):
            _raise_store_error(StoredIndexErrorCode.IO_ERROR)

        runtime_dir = lexical_root.joinpath(*runtime.parts)
        target = runtime_dir / INDEX_FILENAME
        try:
            contained = os.path.commonpath((str(lexical_root), str(target))) == str(
                lexical_root
            )
        except ValueError:
            contained = False
        if (
            not contained
            or target.name != INDEX_FILENAME
            or len(str(target)) > MAX_STORE_PATH_CHARS
        ):
            _raise_store_error(StoredIndexErrorCode.IO_ERROR)

        self._project_root = lexical_root
        self._runtime_parts = runtime.parts
        self._runtime_dir = runtime_dir
        self._target = target
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        return "VectorIndexStore()"

    def _validate_root(self) -> None:
        try:
            metadata = _validate_directory(self._project_root)
            resolved = self._project_root.resolve(strict=True)
        except VectorIndexStoreError:
            raise
        except (OSError, RuntimeError):
            _raise_store_error(StoredIndexErrorCode.IO_ERROR)
        if _is_reparse(metadata) or os.path.normcase(str(resolved)) != os.path.normcase(
            str(self._project_root)
        ):
            _raise_store_error(StoredIndexErrorCode.IO_ERROR)

    def _runtime_directory(self, *, create: bool) -> Path:
        self._validate_root()
        current = self._project_root
        for part in self._runtime_parts:
            current = current / part
            try:
                _validate_directory(current)
            except FileNotFoundError:
                if not create:
                    _raise_store_error(StoredIndexErrorCode.MISSING)
                try:
                    _create_directory(current)
                    _validate_directory(current)
                except VectorIndexStoreError:
                    raise
                except OSError:
                    _raise_store_error(StoredIndexErrorCode.IO_ERROR)
            except VectorIndexStoreError:
                raise
            except OSError:
                _raise_store_error(StoredIndexErrorCode.IO_ERROR)
        if current != self._runtime_dir:
            _raise_store_error(StoredIndexErrorCode.IO_ERROR)
        self._validate_runtime_chain()
        return current

    def _validate_runtime_chain(self) -> None:
        """Recheck every component and resolved containment after any creation."""

        self._validate_root()
        current = self._project_root
        for part in self._runtime_parts:
            current = current / part
            try:
                _validate_directory(current)
            except VectorIndexStoreError:
                raise
            except OSError:
                _raise_store_error(StoredIndexErrorCode.IO_ERROR)
        try:
            resolved = current.resolve(strict=True)
        except (OSError, RuntimeError):
            _raise_store_error(StoredIndexErrorCode.IO_ERROR)
        if os.path.normcase(str(resolved)) != os.path.normcase(str(self._runtime_dir)):
            _raise_store_error(StoredIndexErrorCode.IO_ERROR)

    def prepare(self) -> None:
        """Explicitly create and verify the bounded runtime directory chain."""

        with self._lock:
            self._runtime_directory(create=True)

    def _target_metadata(self, *, missing_ok: bool) -> os.stat_result | None:
        try:
            return _validate_regular(self._target)
        except FileNotFoundError:
            if missing_ok:
                return None
            _raise_store_error(StoredIndexErrorCode.MISSING)
        except VectorIndexStoreError:
            raise
        except OSError:
            _raise_store_error(StoredIndexErrorCode.IO_ERROR)

    def _bounded_read_locked(self) -> bytes:
        self._runtime_directory(create=False)
        before = self._target_metadata(missing_ok=False)
        assert before is not None
        if before.st_size < 0 or before.st_size > MAX_CANONICAL_ARTIFACT_BYTES:
            _raise_store_error(StoredIndexErrorCode.CORRUPT)

        fd = -1
        close_error = False
        try:
            try:
                fd = _open_read(self._target)
                opened = os.fstat(fd)
            except FileNotFoundError:
                _raise_store_error(StoredIndexErrorCode.MISSING)
            except VectorIndexStoreError:
                raise
            except OSError:
                _raise_store_error(StoredIndexErrorCode.IO_ERROR)
            if (
                _is_reparse(opened)
                or not stat.S_ISREG(opened.st_mode)
                or not _same_identity(before, opened)
            ):
                _raise_store_error(StoredIndexErrorCode.IO_ERROR)

            chunks: list[bytes] = []
            total = 0
            while total <= MAX_CANONICAL_ARTIFACT_BYTES:
                try:
                    chunk = _read_chunk(fd, min(64 * 1_024, MAX_CANONICAL_ARTIFACT_BYTES + 1 - total))
                except OSError:
                    _raise_store_error(StoredIndexErrorCode.IO_ERROR)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            if total > MAX_CANONICAL_ARTIFACT_BYTES:
                _raise_store_error(StoredIndexErrorCode.CORRUPT)
            try:
                after_fd = os.fstat(fd)
                after_path = _validate_regular(self._target)
            except VectorIndexStoreError:
                raise
            except OSError:
                _raise_store_error(StoredIndexErrorCode.IO_ERROR)
            if (
                not _same_identity(before, after_fd)
                or not _same_identity(before, after_path)
                or after_fd.st_size != before.st_size
                or total != before.st_size
            ):
                _raise_store_error(StoredIndexErrorCode.IO_ERROR)
            return b"".join(chunks)
        finally:
            if fd >= 0:
                try:
                    _close_fd(fd)
                except OSError:
                    close_error = True
            if close_error:
                _raise_store_error(StoredIndexErrorCode.IO_ERROR)

    def read(self) -> bytes:
        """Return bounded exact bytes without parsing or path disclosure."""

        with self._lock:
            return self._bounded_read_locked()

    @staticmethod
    def _facts(raw: bytes, artifact: VectorIndexArtifact) -> StoredIndexFacts:
        return StoredIndexFacts(
            artifact_sha256=vector_index_sha256(raw),
            format=artifact.format,
            document_count=len(artifact.entries),
            dimensions=artifact.dimensions,
        )

    def load_validated(
        self,
        corpus: Corpus,
        corpus_sha256: str,
        health: OllamaHealthFacts,
    ) -> LoadedVectorIndex:
        """Read, parse, then bind; never rebuild or fall back implicitly."""

        with self._lock:
            raw = self._bounded_read_locked()
            try:
                artifact = load_canonical_vector_index(raw)
            except VectorIndexError:
                _raise_store_error(StoredIndexErrorCode.CORRUPT)
            try:
                validated = validate_vector_index_binding(
                    artifact,
                    corpus,
                    corpus_sha256,
                    health,
                )
            except VectorIndexError:
                _raise_store_error(StoredIndexErrorCode.STALE)
            return LoadedVectorIndex(
                validated_index=validated,
                facts=self._facts(raw, artifact),
            )

    def _owned_temp_metadata(self, path: Path, expected: os.stat_result) -> os.stat_result:
        if path.parent != self._runtime_dir:
            _raise_store_error(StoredIndexErrorCode.IO_ERROR)
        try:
            actual = _validate_regular(path)
        except VectorIndexStoreError:
            raise
        except OSError:
            _raise_store_error(StoredIndexErrorCode.IO_ERROR)
        if not _same_identity(actual, expected):
            _raise_store_error(StoredIndexErrorCode.IO_ERROR)
        return actual

    def _cleanup_owned(self, path: Path, expected: os.stat_result) -> None:
        self._validate_runtime_chain()
        self._owned_temp_metadata(path, expected)
        try:
            _unlink_path(path)
        except OSError:
            _raise_store_error(StoredIndexErrorCode.IO_ERROR)

    def _pre_replace_validate(
        self,
        temp_path: Path,
        temp_metadata: os.stat_result,
        target_metadata: os.stat_result | None,
    ) -> None:
        self._runtime_directory(create=False)
        self._owned_temp_metadata(temp_path, temp_metadata)
        current = self._target_metadata(missing_ok=True)
        if (current is None) != (target_metadata is None) or (
            current is not None
            and target_metadata is not None
            and not _same_identity(current, target_metadata)
        ):
            _raise_store_error(StoredIndexErrorCode.IO_ERROR)

    def _post_replace_validate(self, raw: bytes, digest: str) -> None:
        metadata = self._target_metadata(missing_ok=False)
        if metadata is None or _is_reparse(metadata) or not stat.S_ISREG(metadata.st_mode):
            _raise_store_error(StoredIndexErrorCode.IO_ERROR)
        actual = self._bounded_read_locked()
        if actual != raw or vector_index_sha256(actual) != digest:
            _raise_store_error(StoredIndexErrorCode.IO_ERROR)

    def write(self, artifact: VectorIndexArtifact) -> StoredIndexFacts:
        """Atomically replace the fixed artifact after an explicit caller request."""

        with self._lock:
            try:
                raw = canonical_vector_index_bytes(artifact)
                digest = vector_index_sha256(raw)
            except VectorIndexError:
                _raise_store_error(StoredIndexErrorCode.CORRUPT)

            self._runtime_directory(create=True)
            target_metadata = self._target_metadata(missing_ok=True)
            temp_path: Path | None = None
            temp_metadata: os.stat_result | None = None
            raw_fd = -1
            stream: BinaryIO | None = None
            committed = False
            try:
                try:
                    raw_fd, temp_path = _create_exclusive_temp(
                        self._runtime_dir,
                        "vector-index.write",
                    )
                    temp_metadata = _fstat_fd(raw_fd)
                    if _is_reparse(temp_metadata) or not stat.S_ISREG(temp_metadata.st_mode):
                        _raise_store_error(StoredIndexErrorCode.IO_ERROR)
                    stream = _fdopen_write(raw_fd)
                    raw_fd = -1
                    _write_all(stream, raw)
                    _flush_stream(stream)
                    _fsync_stream(stream)
                    _close_stream(stream)
                    stream = None
                    self._owned_temp_metadata(temp_path, temp_metadata)
                    self._pre_replace_validate(temp_path, temp_metadata, target_metadata)
                    _replace_path(temp_path, self._target)
                    committed = True
                    temp_path = None
                    self._post_replace_validate(raw, digest)
                    return self._facts(raw, artifact)
                except VectorIndexStoreError:
                    raise
                except (OSError, ValueError, TypeError):
                    _raise_store_error(StoredIndexErrorCode.IO_ERROR)
            except VectorIndexStoreError:
                if raw_fd >= 0:
                    try:
                        _close_fd(raw_fd)
                        raw_fd = -1
                    except OSError:
                        pass
                if stream is not None:
                    try:
                        _close_stream(stream)
                    except OSError:
                        pass
                if not committed and temp_path is not None and temp_metadata is not None:
                    self._cleanup_owned(temp_path, temp_metadata)
                    temp_path = None
                raise
