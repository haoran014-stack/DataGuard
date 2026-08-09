"""Subprocess tests for the official Stage 1 module validation entry point."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def writable_tmp_path() -> Path:
    base = PROJECT_ROOT / ".pytest_cache" / "dataguard-cli-tests"
    base.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=base) as directory:
        yield Path(directory)


def run_cli(project_root: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "dataguard.validation",
            "--project-root",
            str(project_root),
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def copy_validation_inputs(destination: Path) -> Path:
    project = destination / "project"
    shutil.copytree(PROJECT_ROOT / "data", project / "data")
    shutil.copytree(PROJECT_ROOT / "docs" / "contracts", project / "docs" / "contracts")
    return project


def test_cli_success_is_deterministic_closed_json() -> None:
    first = run_cli(PROJECT_ROOT)
    second = run_cli(PROJECT_ROOT)

    assert first.returncode == 0
    assert first.stderr == ""
    assert first.stdout == second.stdout
    payload = json.loads(first.stdout)
    assert set(payload) == {
        "stage",
        "version",
        "counts",
        "identity_sha256",
        "corpus_sha256",
        "scenario_sha256",
        "issue_count",
        "status",
    }
    assert payload["stage"] == "stage1"
    assert payload["version"] == "synthetic-v1"
    assert payload["counts"] == {"identities": 6, "documents": 30, "scenarios": 62}
    assert payload["issue_count"] == 0
    assert payload["status"] == "ok"
    for name, output_field in (
        ("identities.yaml", "identity_sha256"),
        ("corpus.yaml", "corpus_sha256"),
        ("scenarios.yaml", "scenario_sha256"),
    ):
        raw = (PROJECT_ROOT / "data" / "synthetic-v1" / name).read_bytes()
        assert payload[output_field] == hashlib.sha256(raw).hexdigest()


def test_cli_structural_failure_is_minimized_and_nonzero(
    writable_tmp_path: Path,
) -> None:
    project = copy_validation_inputs(writable_tmp_path)
    identity_path = project / "data" / "synthetic-v1" / "identities.yaml"
    raw_token = "DO_NOT_ECHO_RAW_ROLE"
    identity_path.write_bytes(
        identity_path.read_bytes().replace(b"role: guest", f"role: {raw_token}".encode(), 1)
    )

    result = run_cli(project)
    payload = json.loads(result.stdout)

    assert result.returncode == 1
    assert result.stderr == ""
    assert payload["status"] == "failed"
    assert payload["issue_count"] == len(payload["issues"])
    assert "schema_validation_error" in {issue["code"] for issue in payload["issues"]}
    assert raw_token not in result.stdout


def test_cli_semantic_failure_is_stable_and_does_not_echo_reference(
    writable_tmp_path: Path,
) -> None:
    project = copy_validation_inputs(writable_tmp_path)
    scenario_path = project / "data" / "synthetic-v1" / "scenarios.yaml"
    raw_token = "UnknownSyntheticSubject"
    scenario_path.write_bytes(
        scenario_path.read_bytes().replace(
            b"subject_id: guest-01",
            f"subject_id: {raw_token}".encode(),
            1,
        )
    )

    first = run_cli(project)
    second = run_cli(project)
    payload = json.loads(first.stdout)

    assert first.returncode == 1
    assert first.stdout == second.stdout
    assert "semantic_unknown_scenario_subject" in {
        issue["code"] for issue in payload["issues"]
    }
    assert raw_token not in first.stdout


def test_cli_includes_closed_error_catalog_validation(writable_tmp_path: Path) -> None:
    project = copy_validation_inputs(writable_tmp_path)
    catalog_path = project / "docs" / "contracts" / "error-codes.yaml"
    raw_token = "DO_NOT_ECHO_CHANGED_REPLY"
    raw = catalog_path.read_text(encoding="utf-8")
    fixed_reply = (
        "The response was blocked by DataGuard policy. / 响应已被 DataGuard 防护策略阻断。"
    )
    catalog_path.write_text(
        raw.replace(fixed_reply, raw_token, 1),
        encoding="utf-8",
        newline="\n",
    )

    result = run_cli(project)
    payload = json.loads(result.stdout)

    assert result.returncode == 1
    assert "error_catalog_invalid" in {issue["code"] for issue in payload["issues"]}
    assert raw_token not in result.stdout

