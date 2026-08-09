"""Deterministic Stage 1 validation command-line entry point."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from dataguard.validation.error_semantic import load_error_catalog
from dataguard.validation.issues import ValidationIssue, stable_issue_order
from dataguard.validation.loading import load_fixture_bundle
from dataguard.validation.semantic import validate_fixture_semantics


STAGE = "stage1"
VERSION = "synthetic-v1"


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m dataguard.validation",
        description="Validate the committed DataGuard Stage 1 contracts and synthetic fixtures.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root containing data/ and docs/contracts/ (default: current directory).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    project_root = args.project_root.resolve()

    bundle_result = load_fixture_bundle(project_root)
    catalog_result = load_error_catalog(
        project_root / "docs" / "contracts" / "error-codes.yaml"
    )
    issues: list[ValidationIssue] = [*bundle_result.issues, *catalog_result.issues]
    if bundle_result.bundle is not None:
        issues.extend(validate_fixture_semantics(bundle_result.bundle))
    ordered_issues = tuple(sorted(set(issues), key=stable_issue_order))

    if ordered_issues:
        _emit(
            {
                "issue_count": len(ordered_issues),
                "issues": [issue.as_dict() for issue in ordered_issues],
                "stage": STAGE,
                "status": "failed",
                "version": VERSION,
            }
        )
        return 1

    bundle = bundle_result.bundle
    if bundle is None:  # Defensive: the loader contract pairs missing data with issues.
        issue = ValidationIssue.create("fixture_read_error", ("bundle",))
        _emit(
            {
                "issue_count": 1,
                "issues": [issue.as_dict()],
                "stage": STAGE,
                "status": "failed",
                "version": VERSION,
            }
        )
        return 1

    _emit(
        {
            "corpus_sha256": bundle.corpus_sha256,
            "counts": {
                "documents": len(bundle.corpus.documents),
                "identities": len(bundle.identities.identities),
                "scenarios": len(bundle.scenarios.scenarios),
            },
            "identity_sha256": bundle.identity_sha256,
            "issue_count": 0,
            "scenario_sha256": bundle.scenario_sha256,
            "stage": STAGE,
            "status": "ok",
            "version": VERSION,
        }
    )
    return 0

