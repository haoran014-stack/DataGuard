"""Explicit artifact preparation commands; never run from API startup."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from dataguard.config import RuntimeProfile, RuntimeSettings, StorageBackend
from dataguard.evaluation import create_evaluation_context
from dataguard.ollama import OllamaClient
from dataguard.production import _manifest, _read_json, _read_runtime_manifest
from dataguard.resources import load_security_resources
from dataguard.validation import load_fixture_bundle
from dataguard.validation.cli import main as validate_main
from dataguard.vector_index import (
    StoredIndexErrorCode, VectorIndexStore, VectorIndexStoreError, build_vector_index,
)


MANIFEST_FILENAME = "experiment-manifest.v1.json"


def _emit(status: str, operation: str, **facts: object) -> None:
    print(json.dumps({"operation": operation, "status": status, **facts},
                     sort_keys=True, separators=(",", ":")))


def _settings() -> RuntimeSettings:
    return RuntimeSettings.from_env({key: value for key, value in os.environ.items()
        if key.startswith("DATAGUARD_") and key != "DATAGUARD_PROJECT_ROOT"})


def _bundle(root: Path):
    result = load_fixture_bundle(root)
    if not result.ok or result.bundle is None:
        raise ValueError
    return result.bundle


def _manifest_path(root: Path, settings: RuntimeSettings) -> Path:
    relative = settings.experiment_manifest_path or settings.runtime_state_dir / MANIFEST_FILENAME
    target = root / relative
    root_resolved = root.resolve(strict=True)
    current = root_resolved
    for part in relative.parent.parts:
        current = current / part
        metadata = current.lstat()
        if current.is_symlink() or getattr(metadata, "st_file_attributes", 0) & 0x400 \
                or not current.is_dir():
            raise ValueError
    parent = target.parent.resolve(strict=True)
    if root_resolved not in parent.parents and parent != root_resolved:
        raise ValueError
    if target.exists():
        metadata = target.lstat()
        if target.is_symlink() or getattr(metadata, "st_file_attributes", 0) & 0x400 \
                or not target.is_file():
            raise ValueError
    return target


def _atomic_write(target: Path, raw: bytes, overwrite: bool) -> None:
    if target.exists() and not overwrite:
        raise FileExistsError
    temp = target.parent / (".manifest." + os.urandom(12).hex() + ".tmp")
    descriptor = -1
    try:
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, target)
    finally:
        if descriptor >= 0:
            try: os.close(descriptor)
            except OSError: pass
        if temp.exists():
            try: temp.unlink()
            except OSError: pass


async def _build(root: Path, overwrite: bool) -> None:
    settings = _settings(); bundle = _bundle(root)
    store = VectorIndexStore(root, settings)
    try: store.read()
    except VectorIndexStoreError as error:
        if error.code is StoredIndexErrorCode.MISSING:
            exists = False
        elif overwrite:
            exists = True
        else:
            raise
    else: exists = True
    if exists and not overwrite: raise FileExistsError
    async with OllamaClient(settings) as client:
        health = await client.probe()
        artifact = await build_vector_index(bundle.corpus, bundle.corpus_sha256, health, client)
    facts = store.write(artifact)
    _emit("ok", "build-index", artifact_sha256=facts.artifact_sha256,
          dimensions=facts.dimensions, documents=facts.document_count)


async def _generate_manifest(root: Path, overwrite: bool) -> None:
    settings = _settings()
    if settings.profile is not RuntimeProfile.EVIDENCE \
            or settings.storage_backend is not StorageBackend.POSTGRESQL:
        raise ValueError
    bundle = _bundle(root); resources = load_security_resources()
    async with OllamaClient(settings) as client:
        health = await client.probe()
    loaded = VectorIndexStore(root, settings).load_validated(
        bundle.corpus, bundle.corpus_sha256, health)
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    manifest = _manifest(bundle, resources, loaded, health, settings, created_at)
    report_schema = _read_json(root / "docs/contracts/report.schema.json")
    manifest_schema = _read_json(root / "docs/contracts/experiment-manifest.schema.json")
    create_evaluation_context(bundle, resources, loaded, health, settings,
                              manifest, report_schema, manifest_schema)
    raw = json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    target = _manifest_path(root, settings)
    _atomic_write(target, raw, overwrite)
    _emit("ok", "generate-manifest", manifest_sha256=__import__("hashlib").sha256(raw).hexdigest())


async def _verify(root: Path) -> None:
    settings = _settings(); bundle = _bundle(root); resources = load_security_resources()
    async with OllamaClient(settings) as client:
        health = await client.probe()
    loaded = VectorIndexStore(root, settings).load_validated(
        bundle.corpus, bundle.corpus_sha256, health)
    if settings.profile is RuntimeProfile.EVIDENCE:
        if settings.experiment_manifest_path is None: raise ValueError
        manifest = _read_runtime_manifest(root, settings.experiment_manifest_path)
        create_evaluation_context(bundle, resources, loaded, health, settings, manifest,
            _read_json(root / "docs/contracts/report.schema.json"),
            _read_json(root / "docs/contracts/experiment-manifest.schema.json"))
    _emit("ok", "verify-artifacts", artifact_sha256=loaded.facts.artifact_sha256,
          profile=settings.profile.value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dataguard")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate")
    for name in ("build-index", "generate-manifest"):
        item = commands.add_parser(name); item.add_argument("--overwrite", action="store_true")
    commands.add_parser("verify-artifacts")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv); root = args.project_root.resolve()
    if args.command == "validate":
        return validate_main(["--project-root", str(root)])
    try:
        if args.command == "build-index": asyncio.run(_build(root, args.overwrite))
        elif args.command == "generate-manifest": asyncio.run(_generate_manifest(root, args.overwrite))
        else: asyncio.run(_verify(root))
        return 0
    except Exception:
        _emit("failed", args.command, code="artifact_preparation_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
