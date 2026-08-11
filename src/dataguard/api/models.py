"""Closed HTTP request and response DTOs for the six public operations."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from dataguard.domain.models import SubjectId
from dataguard.rag.models import RagMode
from dataguard.storage.models import EvaluationProfile
from dataguard.storage.models import ErrorCode

DataVersion = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=64,
                                                pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
UuidText = Annotated[str, StringConstraints(strict=True, min_length=36, max_length=36)]


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True,
                              hide_input_in_errors=True, allow_inf_nan=False)


def canonical_uuid(value: Any) -> str:
    if type(value) is not str:
        raise ValueError("identifier is invalid")
    try:
        parsed = UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise ValueError("identifier is invalid") from None
    if str(parsed) != value:
        raise ValueError("identifier is invalid")
    return value


def aware_utc(value: Any) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp is invalid")
    return value.astimezone(timezone.utc)


class ChatRequest(_Closed):
    subject_id: SubjectId
    question: str = Field(strict=True, min_length=1, max_length=2000, repr=False)
    mode: RagMode
    corpus_version: DataVersion


class ChatOutcome(str, Enum):
    ANSWERED = "answered"
    BLOCKED = "blocked"


class ChatResponse(_Closed):
    reply: str = Field(strict=True, repr=False)
    trace_id: UuidText
    outcome: ChatOutcome

    @field_validator("trace_id", mode="before")
    @classmethod
    def validate_trace(cls, value: Any) -> str:
        return canonical_uuid(value)


class EvaluationRunRequest(_Closed):
    scenario_set_version: DataVersion
    profile: EvaluationProfile


class EvaluationRunAccepted(_Closed):
    run_id: UuidText
    status: Literal["queued"]

    @field_validator("run_id", mode="before")
    @classmethod
    def validate_run(cls, value: Any) -> str:
        return canonical_uuid(value)


class ModelHealth(_Closed):
    tag: str = Field(strict=True, max_length=64)
    digest: Annotated[str, StringConstraints(strict=True, pattern=r"^(sha256:)?[a-f0-9]{64}$")] | None
    available: bool = Field(strict=True)


class OllamaHealth(_Closed):
    status: Literal["up", "down"]
    version: str | None = Field(default=None, max_length=64, strict=True)
    generation_model: ModelHealth
    embedding_model: ModelHealth

    @model_validator(mode="after")
    def fixed_model_tags(self) -> Self:
        if (self.generation_model.tag != "qwen2.5:3b-instruct"
                or self.embedding_model.tag != "qwen3-embedding:0.6b"):
            raise ValueError("health model tags are invalid")
        return self


class StorageHealth(_Closed):
    status: Literal["up", "down"]
    backend: Literal["sqlite", "postgresql", "unavailable"]


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HealthReason(str, Enum):
    OLLAMA_UNAVAILABLE = "ollama_unavailable"
    OLLAMA_VERSION_MISMATCH = "ollama_version_mismatch"
    GENERATION_MODEL_UNAVAILABLE = "generation_model_unavailable"
    EMBEDDING_MODEL_UNAVAILABLE = "embedding_model_unavailable"
    GENERATION_MODEL_DIGEST_MISMATCH = "generation_model_digest_mismatch"
    EMBEDDING_MODEL_DIGEST_MISMATCH = "embedding_model_digest_mismatch"
    STORAGE_UNAVAILABLE = "storage_unavailable"
    STORAGE_NOT_POSTGRESQL = "storage_not_postgresql"
    EXPERIMENT_MANIFEST_NOT_LOADED = "experiment_manifest_not_loaded"
    EXPERIMENT_MANIFEST_MISMATCH = "experiment_manifest_mismatch"


class HealthResponse(_Closed):
    status: HealthStatus
    api_version: Literal["v1"]
    ollama: OllamaHealth
    storage: StorageHealth
    evidence_readiness: bool = Field(strict=True)
    reasons: tuple[HealthReason, ...]
    checked_at: datetime

    @field_validator("checked_at", mode="before")
    @classmethod
    def normalize_checked_at(cls, value: Any) -> datetime:
        return aware_utc(value)

    @model_validator(mode="after")
    def coherent_status(self) -> Self:
        if len(self.reasons) != len(set(self.reasons)):
            raise ValueError("health reasons are duplicated")
        if self.status is HealthStatus.HEALTHY:
            valid = self.evidence_readiness and not self.reasons and self.ollama.status == "up" and self.storage.status == "up"
        elif self.status is HealthStatus.DEGRADED:
            valid = not self.evidence_readiness and bool(self.reasons) and self.ollama.status == "up" and self.storage.status == "up"
        else:
            valid = not self.evidence_readiness and bool(self.reasons) and (self.ollama.status == "down" or self.storage.status == "down")
        if not valid:
            raise ValueError("health status is inconsistent")
        return self


class ProblemDetails(_Closed):
    type: str = Field(strict=True, pattern=r"^https://dataguard\.local/problems/[a-z0-9_-]+$")
    title: str = Field(strict=True, min_length=1, max_length=128)
    status: int = Field(strict=True, ge=400, le=599)
    detail: str = Field(strict=True, min_length=1, max_length=512)
    code: ErrorCode
    trace_id: UuidText
    retryable: bool = Field(strict=True)

    @field_validator("trace_id", mode="before")
    @classmethod
    def validate_trace(cls, value: Any) -> str:
        return canonical_uuid(value)
