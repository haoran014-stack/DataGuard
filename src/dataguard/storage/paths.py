"""Filesystem boundary for the local SQLite audit database."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from dataguard.config import RuntimeSettings, StorageBackend
from .errors import StorageError

_REPARSE_ATTRIBUTE = 0x400


def _is_reparse(info: os.stat_result) -> bool:
    return bool(getattr(info, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE)


def _safe_lstat(path: Path) -> os.stat_result:
    try:
        return path.lstat()
    except OSError:
        raise StorageError() from None


def _real_directory(path: Path) -> None:
    info = _safe_lstat(path)
    if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or _is_reparse(info):
        raise StorageError()


def _contained(root: Path, target: Path) -> bool:
    try:
        return os.path.commonpath((str(root), str(target))) == str(root)
    except (ValueError, OSError):
        return False


@dataclass(frozen=True, slots=True, repr=False)
class SafeSQLiteLocation:
    """Lexically validated location; filesystem checks occur only on prepare/use."""

    project_root: Path
    target: Path

    def __repr__(self) -> str:
        return "SafeSQLiteLocation()"

    @classmethod
    def from_settings(cls, project_root: Path, settings: RuntimeSettings) -> "SafeSQLiteLocation":
        if settings.storage_backend is not StorageBackend.SQLITE or not isinstance(project_root, Path):
            raise StorageError()
        if not project_root.is_absolute():
            raise StorageError()
        prefix = "sqlite+pysqlite:///"
        dsn = settings.database_dsn_value()
        if not dsn.startswith(prefix):
            raise StorageError()
        relative = Path(dsn[len(prefix):])
        if relative.is_absolute() or relative.parts[:1] != ("artifacts",) or any(part in {"", ".", ".."} for part in relative.parts):
            raise StorageError()
        root = Path(os.path.abspath(project_root))
        target = Path(os.path.abspath(root / relative))
        if len(str(target)) > 32_767 or not _contained(root, target):
            raise StorageError()
        return cls(root, target)

    def prepare_parent(self) -> None:
        """Create missing descendants one at a time and reject link/reparse traversal."""

        _real_directory(self.project_root)
        try:
            if self.project_root.resolve(strict=True) != self.project_root:
                raise StorageError()
        except OSError:
            raise StorageError() from None
        current = self.project_root
        relative_parent = self.target.parent.relative_to(self.project_root)
        for part in relative_parent.parts:
            current = current / part
            try:
                info = current.lstat()
            except FileNotFoundError:
                try:
                    current.mkdir(mode=0o700)
                except OSError:
                    raise StorageError() from None
                info = _safe_lstat(current)
            except OSError:
                raise StorageError() from None
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or _is_reparse(info):
                raise StorageError()
            try:
                resolved = current.resolve(strict=True)
            except OSError:
                raise StorageError() from None
            if not _contained(self.project_root, resolved):
                raise StorageError()
        self.validate_target(allow_missing=True)

    def validate_project_root(self) -> None:
        """Read-only validation of the configured existing repository root."""

        _real_directory(self.project_root)
        try:
            if self.project_root.resolve(strict=True) != self.project_root:
                raise StorageError()
        except OSError:
            raise StorageError() from None

    def validate_parent_chain(self) -> None:
        """Read-only validation of every existing parent component."""

        self.validate_project_root()
        current = self.project_root
        for part in self.target.parent.relative_to(self.project_root).parts:
            current = current / part
            info = _safe_lstat(current)
            if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode) or _is_reparse(info):
                raise StorageError()
            try:
                resolved = current.resolve(strict=True)
            except OSError:
                raise StorageError() from None
            if not _contained(self.project_root, resolved):
                raise StorageError()

    def validate_target(self, *, allow_missing: bool) -> None:
        try:
            info = self.target.lstat()
        except FileNotFoundError:
            if allow_missing:
                return
            raise StorageError() from None
        except OSError:
            raise StorageError() from None
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or _is_reparse(info)
            or getattr(info, "st_nlink", 1) != 1
        ):
            raise StorageError()
        try:
            resolved = self.target.resolve(strict=True)
        except OSError:
            raise StorageError() from None
        if not _contained(self.project_root, resolved):
            raise StorageError()
