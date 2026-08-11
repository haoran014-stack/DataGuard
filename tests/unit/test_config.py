from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from pydantic import ValidationError

from dataguard.config import (
    DEFAULT_OLLAMA_BASE_URL,
    MAX_CONNECT_TIMEOUT_SECONDS,
    MAX_READ_TIMEOUT_SECONDS,
    MAX_RESPONSE_BYTES,
    MIN_CONNECT_TIMEOUT_SECONDS,
    MIN_READ_TIMEOUT_SECONDS,
    MIN_RESPONSE_BYTES,
    RuntimeProfile,
    RuntimeSettings,
    StorageBackend,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def writable_tmp_path() -> Path:
    base = PROJECT_ROOT / ".pytest_cache" / "dataguard-config-tests"
    base.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=base) as directory:
        yield Path(directory)


def test_defaults_are_closed_local_exploratory_sqlite() -> None:
    settings = RuntimeSettings()

    assert settings.profile is RuntimeProfile.EXPLORATORY
    assert settings.storage_backend is StorageBackend.SQLITE
    assert settings.ollama_base_url == DEFAULT_OLLAMA_BASE_URL
    assert settings.runtime_state_dir == Path("artifacts/runtime")
    assert settings.database_dsn_value().startswith("sqlite+pysqlite:///")
    with pytest.raises(ValidationError):
        RuntimeSettings(unknown_setting=True)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("http://localhost:11434", "http://localhost:11434"),
        ("http://127.0.0.1:11434/", "http://127.0.0.1:11434"),
        ("http://[::1]:11434", "http://[::1]:11434"),
    ],
)
def test_ollama_url_accepts_only_literal_loopback_forms(value: str, expected: str) -> None:
    assert RuntimeSettings(ollama_base_url=value).ollama_base_url == expected


@pytest.mark.parametrize(
    "value",
    [
        "https://127.0.0.1:11434",
        "ftp://localhost:11434",
        "http://127.0.0.2:11434",
        "http://0.0.0.0:11434",
        "http://example.invalid:11434",
        "http://user:pass@localhost:11434",
        "http://localhost:11434?debug=true",
        "http://localhost:11434?",
        "http://localhost:11434#fragment",
        "http://localhost:11434#",
        "http://localhost:11434/api",
        "http://localhost:",
        "http://localhost:0",
        " http://localhost:11434",
    ],
)
def test_ollama_url_rejects_remote_or_ambiguous_forms(value: str) -> None:
    with pytest.raises(ValidationError):
        RuntimeSettings(ollama_base_url=value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ollama_connect_timeout_seconds", MIN_CONNECT_TIMEOUT_SECONDS / 2),
        ("ollama_connect_timeout_seconds", MAX_CONNECT_TIMEOUT_SECONDS + 1),
        ("ollama_read_timeout_seconds", MIN_READ_TIMEOUT_SECONDS / 2),
        ("ollama_read_timeout_seconds", MAX_READ_TIMEOUT_SECONDS + 1),
        ("ollama_max_response_bytes", MIN_RESPONSE_BYTES - 1),
        ("ollama_max_response_bytes", MAX_RESPONSE_BYTES + 1),
    ],
)
def test_numeric_safety_bounds_reject_out_of_range(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        RuntimeSettings(**{field: value})


def test_numeric_safety_bounds_accept_exact_edges() -> None:
    settings = RuntimeSettings(
        ollama_connect_timeout_seconds=MIN_CONNECT_TIMEOUT_SECONDS,
        ollama_read_timeout_seconds=MAX_READ_TIMEOUT_SECONDS,
        ollama_max_response_bytes=MAX_RESPONSE_BYTES,
    )

    assert settings.ollama_connect_timeout_seconds == MIN_CONNECT_TIMEOUT_SECONDS
    assert settings.ollama_read_timeout_seconds == MAX_READ_TIMEOUT_SECONDS
    assert settings.ollama_max_response_bytes == MAX_RESPONSE_BYTES


@pytest.mark.parametrize(
    "value",
    [
        "runtime",
        "../artifacts/runtime",
        "artifacts/../secrets",
        "C:/outside/runtime",
        "/outside/runtime",
        "artifacts/" + "x" * 241,
    ],
)
def test_runtime_path_must_remain_bounded_beneath_artifacts(value: str) -> None:
    with pytest.raises(ValidationError):
        RuntimeSettings(runtime_state_dir=value)


def test_evidence_profile_requires_postgresql() -> None:
    with pytest.raises(ValidationError):
        RuntimeSettings(profile=RuntimeProfile.EVIDENCE)

    settings = RuntimeSettings(
        profile=RuntimeProfile.EVIDENCE,
        storage_backend=StorageBackend.POSTGRESQL,
        database_dsn=(
            "postgresql+psycopg://synthetic-user:synthetic-pass@localhost:5432/dataguard"
        ),
    )
    assert settings.profile is RuntimeProfile.EVIDENCE
    assert settings.storage_backend is StorageBackend.POSTGRESQL


@pytest.mark.parametrize("port", ["bad", "0", "65536"])
def test_postgresql_port_is_bounded_and_errors_do_not_echo_dsn(port: str) -> None:
    dsn = f"postgresql+psycopg://synthetic-user:do-not-echo@localhost:{port}/dataguard"
    with pytest.raises(ValidationError) as captured:
        RuntimeSettings(
            storage_backend=StorageBackend.POSTGRESQL,
            database_dsn=dsn,
        )

    assert dsn not in str(captured.value)
    assert "do-not-echo" not in str(captured.value)


def test_database_dsn_is_absent_from_repr_and_serialization() -> None:
    secret = "synthetic-user:synthetic-pass"
    settings = RuntimeSettings(
        storage_backend=StorageBackend.POSTGRESQL,
        database_dsn=f"postgresql+psycopg://{secret}@localhost/dataguard",
    )

    rendered = " ".join(
        [repr(settings), repr(settings.model_dump()), settings.model_dump_json()]
    )
    assert secret not in rendered
    assert "database_dsn" not in settings.model_dump()
    assert "database_dsn" not in settings.model_dump_json()


def test_invalid_database_dsn_is_not_echoed_by_validation_errors() -> None:
    secret = "synthetic-user:do-not-echo"
    with pytest.raises(ValidationError) as captured:
        RuntimeSettings(
            storage_backend=StorageBackend.POSTGRESQL,
            database_dsn=f"http://{secret}@localhost/dataguard",
        )
    assert secret not in str(captured.value)


def test_closed_environment_loader_parses_explicit_values() -> None:
    settings = RuntimeSettings.from_env(
        {
            "DATAGUARD_OLLAMA_BASE_URL": "http://[::1]:11434/",
            "DATAGUARD_OLLAMA_CONNECT_TIMEOUT_SECONDS": "1.5",
            "DATAGUARD_OLLAMA_READ_TIMEOUT_SECONDS": "45",
            "DATAGUARD_OLLAMA_MAX_RESPONSE_BYTES": "4096",
            "DATAGUARD_RUNTIME_STATE_DIR": "artifacts/test-runtime",
        }
    )

    assert settings.ollama_base_url == "http://[::1]:11434"
    assert settings.ollama_connect_timeout_seconds == 1.5
    assert settings.ollama_read_timeout_seconds == 45.0
    assert settings.ollama_max_response_bytes == 4096
    assert settings.runtime_state_dir == Path("artifacts/test-runtime")


def test_closed_environment_loader_rejects_unknown_dataguard_key_without_echo() -> None:
    value = "do-not-echo"
    with pytest.raises(ValueError) as captured:
        RuntimeSettings.from_env({"DATAGUARD_UNKNOWN": value})
    assert value not in str(captured.value)


def test_import_has_no_environment_network_database_or_filesystem_side_effect(
    writable_tmp_path: Path,
) -> None:
    script = """
import pathlib
import socket
import sqlite3

def forbidden(*args, **kwargs):
    raise RuntimeError("side effect attempted")

socket.create_connection = forbidden
socket.socket.connect = forbidden
sqlite3.connect = forbidden
pathlib.Path.mkdir = forbidden
pathlib.Path.touch = forbidden
import dataguard.config
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    environment["DATAGUARD_OLLAMA_BASE_URL"] = "https://example.invalid"
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=writable_tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert list(writable_tmp_path.iterdir()) == []


def test_container_host_gateway_requires_exact_explicit_opt_in() -> None:
    accepted = RuntimeSettings(allow_container_host_gateway=True,
        ollama_base_url="http://host.docker.internal:11434")
    assert accepted.ollama_base_url == "http://host.docker.internal:11434"
    with pytest.raises(ValidationError):
        RuntimeSettings(ollama_base_url="http://host.docker.internal:11434")
    with pytest.raises(ValidationError):
        RuntimeSettings(allow_container_host_gateway=True,
                        ollama_base_url="http://127.0.0.1:11434")
    for value in ("https://host.docker.internal:11434", "http://user@host.docker.internal:11434",
                  "http://host.docker.internal:11434/path", "http://example.internal:11434"):
        with pytest.raises(ValidationError):
            RuntimeSettings(allow_container_host_gateway=True, ollama_base_url=value)


def test_container_gateway_env_boolean_is_closed() -> None:
    settings = RuntimeSettings.from_env({
        "DATAGUARD_ALLOW_CONTAINER_HOST_GATEWAY": "true",
        "DATAGUARD_OLLAMA_BASE_URL": "http://host.docker.internal:11434",
    })
    assert settings.allow_container_host_gateway is True
    with pytest.raises(ValueError):
        RuntimeSettings.from_env({"DATAGUARD_ALLOW_CONTAINER_HOST_GATEWAY": "1"})
