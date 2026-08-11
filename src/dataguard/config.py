"""Closed, side-effect-free configuration for the local Stage 2 runtime.

Importing this module reads no environment variables and performs no network,
database, or filesystem operation. Environment access is explicit through
``RuntimeSettings.from_env``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from enum import Enum
from pathlib import Path
from typing import Any, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_SQLITE_DSN = "sqlite+pysqlite:///artifacts/dataguard.sqlite3"
DEFAULT_RUNTIME_STATE_DIR = Path("artifacts/runtime")

MIN_CONNECT_TIMEOUT_SECONDS = 0.1
MAX_CONNECT_TIMEOUT_SECONDS = 30.0
MIN_READ_TIMEOUT_SECONDS = 1.0
MAX_READ_TIMEOUT_SECONDS = 300.0
MIN_RESPONSE_BYTES = 1_024
MAX_RESPONSE_BYTES = 8 * 1_024 * 1_024
MAX_URL_LENGTH = 256
MAX_DSN_LENGTH = 2_048
MAX_RUNTIME_PATH_LENGTH = 240

_ALLOWED_OLLAMA_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
_ENV_TO_FIELD = {
    "DATAGUARD_PROFILE": "profile",
    "DATAGUARD_STORAGE_BACKEND": "storage_backend",
    "DATAGUARD_DATABASE_DSN": "database_dsn",
    "DATAGUARD_ALLOW_CONTAINER_HOST_GATEWAY": "allow_container_host_gateway",
    "DATAGUARD_OLLAMA_BASE_URL": "ollama_base_url",
    "DATAGUARD_OLLAMA_CONNECT_TIMEOUT_SECONDS": "ollama_connect_timeout_seconds",
    "DATAGUARD_OLLAMA_READ_TIMEOUT_SECONDS": "ollama_read_timeout_seconds",
    "DATAGUARD_OLLAMA_MAX_RESPONSE_BYTES": "ollama_max_response_bytes",
    "DATAGUARD_RUNTIME_STATE_DIR": "runtime_state_dir",
    "DATAGUARD_EXPERIMENT_MANIFEST_PATH": "experiment_manifest_path",
}


class RuntimeProfile(str, Enum):
    """The two locked local experiment profiles."""

    EXPLORATORY = "exploratory"
    EVIDENCE = "evidence"


class StorageBackend(str, Enum):
    """The two approved local storage backends."""

    SQLITE = "sqlite"
    POSTGRESQL = "postgresql"


def _bounded_artifact_path(value: str | Path) -> Path:
    """Validate a repository-relative runtime path without touching the filesystem."""

    path = Path(value)
    rendered = path.as_posix()
    if (
        not rendered
        or len(rendered) > MAX_RUNTIME_PATH_LENGTH
        or path.is_absolute()
        or bool(path.drive)
        or not path.parts
        or path.parts[0] != "artifacts"
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("runtime paths must remain relative beneath artifacts")
    return path


class RuntimeSettings(BaseModel):
    """Closed runtime settings with local-only model and minimized secret handling."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )

    profile: RuntimeProfile = RuntimeProfile.EXPLORATORY
    storage_backend: StorageBackend = StorageBackend.SQLITE
    database_dsn: SecretStr = Field(
        default_factory=lambda: SecretStr(DEFAULT_SQLITE_DSN),
        exclude=True,
        repr=False,
    )
    allow_container_host_gateway: bool = Field(default=False, strict=True)
    ollama_base_url: str = DEFAULT_OLLAMA_BASE_URL
    ollama_connect_timeout_seconds: float = Field(
        default=5.0,
        strict=True,
        ge=MIN_CONNECT_TIMEOUT_SECONDS,
        le=MAX_CONNECT_TIMEOUT_SECONDS,
    )
    ollama_read_timeout_seconds: float = Field(
        default=120.0,
        strict=True,
        ge=MIN_READ_TIMEOUT_SECONDS,
        le=MAX_READ_TIMEOUT_SECONDS,
    )
    ollama_max_response_bytes: int = Field(
        default=2 * 1_024 * 1_024,
        strict=True,
        ge=MIN_RESPONSE_BYTES,
        le=MAX_RESPONSE_BYTES,
    )
    runtime_state_dir: Path = DEFAULT_RUNTIME_STATE_DIR
    experiment_manifest_path: Path | None = None

    @field_validator("ollama_base_url", mode="before")
    @classmethod
    def validate_local_ollama_url(cls, value: Any) -> str:
        """Accept loopback HTTP, plus the exact container gateway under explicit opt-in."""

        if type(value) is not str or not value or value != value.strip():
            raise ValueError("Ollama base URL must be a bounded local HTTP URL")
        if len(value) > MAX_URL_LENGTH:
            raise ValueError("Ollama base URL must be a bounded local HTTP URL")
        try:
            parsed = urlsplit(value)
            port = parsed.port
            username = parsed.username
            password = parsed.password
        except ValueError:
            raise ValueError("Ollama base URL must be a bounded local HTTP URL") from None
        host = parsed.hostname
        allowed_hosts = set(_ALLOWED_OLLAMA_HOSTS)
        if cls is RuntimeSettings:
            # The model-level validator below binds the opt-in to the literal host.
            allowed_hosts.add("host.docker.internal")
        if (
            parsed.scheme != "http"
            or host not in allowed_hosts
            or username is not None
            or password is not None
            or "?" in value
            or "#" in value
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or parsed.netloc.endswith(":")
            or (port is not None and port < 1)
        ):
            raise ValueError("Ollama base URL must be a bounded local HTTP URL")

        normalized_host = "[::1]" if host == "::1" else host
        normalized_port = f":{port}" if port is not None else ""
        return f"http://{normalized_host}{normalized_port}"

    @field_validator("runtime_state_dir", mode="before")
    @classmethod
    def validate_runtime_state_dir(cls, value: Any) -> Path:
        if not isinstance(value, (str, Path)):
            raise ValueError("runtime paths must remain relative beneath artifacts")
        return _bounded_artifact_path(value)

    @field_validator("experiment_manifest_path", mode="before")
    @classmethod
    def validate_manifest_path(cls, value: Any) -> Path | None:
        if value is None:
            return None
        if not isinstance(value, (str, Path)):
            raise ValueError("runtime paths must remain relative beneath artifacts")
        return _bounded_artifact_path(value)

    @model_validator(mode="after")
    def validate_storage_profile(self) -> Self:
        if ((urlsplit(self.ollama_base_url).hostname == "host.docker.internal")
                != self.allow_container_host_gateway):
            raise ValueError("container host gateway access requires an exact explicit opt-in")
        dsn = self.database_dsn.get_secret_value()
        if not dsn or len(dsn) > MAX_DSN_LENGTH:
            raise ValueError("database DSN does not match the selected local backend")

        if self.storage_backend is StorageBackend.SQLITE:
            prefix = "sqlite+pysqlite:///"
            if not dsn.startswith(prefix):
                raise ValueError("database DSN does not match the selected local backend")
            sqlite_path = dsn[len(prefix) :]
            if any(delimiter in sqlite_path for delimiter in ("?", "#")):
                raise ValueError("database DSN does not match the selected local backend")
            try:
                _bounded_artifact_path(sqlite_path)
            except (TypeError, ValueError):
                raise ValueError("database DSN does not match the selected local backend") from None
        else:
            try:
                parsed = urlsplit(dsn)
                port = parsed.port
                valid_postgresql = (
                    parsed.scheme == "postgresql+psycopg"
                    and bool(parsed.hostname)
                    and bool(parsed.path.strip("/"))
                    and not parsed.fragment
                    and (port is None or 1 <= port <= 65_535)
                )
            except ValueError:
                valid_postgresql = False
            if not valid_postgresql:
                raise ValueError("database DSN does not match the selected local backend")

        if (
            self.profile is RuntimeProfile.EVIDENCE
            and self.storage_backend is not StorageBackend.POSTGRESQL
        ):
            raise ValueError("evidence profile requires PostgreSQL storage")
        return self

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Self:
        """Build settings from the closed ``DATAGUARD_*`` namespace on demand."""

        source = os.environ if environ is None else environ
        unknown = {
            key
            for key in source
            if key.startswith("DATAGUARD_") and key not in _ENV_TO_FIELD
        }
        if unknown:
            raise ValueError("unsupported DataGuard environment setting")

        values: dict[str, Any] = {}
        for environment_name, field_name in _ENV_TO_FIELD.items():
            if environment_name not in source:
                continue
            raw = source[environment_name]
            if not isinstance(raw, str):
                raise ValueError("DataGuard environment settings must be strings")
            if field_name in {
                "ollama_connect_timeout_seconds",
                "ollama_read_timeout_seconds",
            }:
                try:
                    values[field_name] = float(raw)
                except ValueError:
                    raise ValueError("DataGuard numeric environment setting is invalid") from None
            elif field_name == "ollama_max_response_bytes":
                try:
                    values[field_name] = int(raw)
                except ValueError:
                    raise ValueError("DataGuard numeric environment setting is invalid") from None
            elif field_name == "allow_container_host_gateway":
                if raw not in {"true", "false"}:
                    raise ValueError("DataGuard boolean environment setting is invalid")
                values[field_name] = raw == "true"
            else:
                values[field_name] = raw
        return cls.model_validate(values)

    def database_dsn_value(self) -> str:
        """Return the DSN only for an internal storage factory at its call site."""

        return self.database_dsn.get_secret_value()
