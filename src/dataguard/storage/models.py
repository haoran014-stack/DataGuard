"""Closed public audit evidence models."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from dataguard.detector.models import DetectionAction, DetectionType
from dataguard.domain.models import ContractId, Role, SubjectId, SYNTHETIC_VERSION
from dataguard.rag.models import RagMode

UuidText = Annotated[str, StringConstraints(strict=True, min_length=36, max_length=36)]


class AuditEventType(str, Enum):
    CHAT_COMPLETED = "chat_completed"
    RETRIEVAL_COMPLETED = "retrieval_completed"
    OUTPUT_DETECTION_COMPLETED = "output_detection_completed"
    RUN_CREATED = "run_created"
    RUN_STATE_CHANGED = "run_state_changed"
    REPORT_GENERATED = "report_generated"


class AuditOutcome(str, Enum):
    ANSWERED = "answered"
    BLOCKED = "blocked"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class AuditDetectorAction(str, Enum):
    NONE = "none"
    OBSERVED = "observed"
    BLOCKED = "blocked"


class ErrorCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    SUBJECT_NOT_FOUND = "subject_not_found"
    CORPUS_NOT_FOUND = "corpus_not_found"
    SCENARIO_SET_NOT_FOUND = "scenario_set_not_found"
    RUN_NOT_FOUND = "run_not_found"
    REPORT_NOT_READY = "report_not_ready"
    REPORT_UNAVAILABLE = "report_unavailable"
    OLLAMA_UNAVAILABLE = "ollama_unavailable"
    GENERATION_MODEL_UNAVAILABLE = "generation_model_unavailable"
    EMBEDDING_MODEL_UNAVAILABLE = "embedding_model_unavailable"
    STORAGE_UNAVAILABLE = "storage_unavailable"
    MODEL_TIMEOUT = "model_timeout"
    MODEL_PROTOCOL_ERROR = "model_protocol_error"
    EXPERIMENT_MANIFEST_MISMATCH = "experiment_manifest_mismatch"
    CONTEXT_BUDGET_EXCEEDED = "context_budget_exceeded"
    INTERNAL_ERROR = "internal_error"


class _ClosedFrozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True,
                              hide_input_in_errors=True, allow_inf_nan=False)


def _uuid(value: Any) -> str:
    if type(value) is not str:
        raise ValueError("identifier must be a canonical UUID")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError, TypeError):
        raise ValueError("identifier must be a canonical UUID") from None
    if value != str(parsed):
        raise ValueError("identifier must be a canonical UUID")
    return value


def _utc(value: Any) -> datetime:
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be UTC aware")
    return value.astimezone(timezone.utc)


class RetrievedDocumentEvidence(_ClosedFrozen):
    document_id: ContractId
    rank: int = Field(strict=True, ge=1, le=4)
    similarity_score: float = Field(strict=True, ge=-1.0, le=1.0)
    authorized: bool = Field(strict=True)
    included_in_context: bool = Field(strict=True)
    denial_reason: Literal["role_not_allowed"] | None = None

    @model_validator(mode="after")
    def validate_reason(self) -> Self:
        if self.denial_reason not in {None, "role_not_allowed"}:
            raise ValueError("denial reason is invalid")
        if self.authorized and self.denial_reason is not None:
            raise ValueError("authorized retrieval cannot have a denial reason")
        return self


class AuthorizationDenial(_ClosedFrozen):
    document_id: ContractId
    reason: Literal["role_not_allowed"]


class DetectionEvidence(_ClosedFrozen):
    type: DetectionType
    evidence_id: ContractId
    violation: bool = Field(strict=True)
    action: DetectionAction

    @model_validator(mode="after")
    def validate_detection(self) -> Self:
        if self.type in {DetectionType.DOCUMENT_CANARY, DetectionType.SYSTEM_CANARY} and not self.violation:
            raise ValueError("Canary evidence must be a violation")
        if self.action is DetectionAction.BLOCKED and not self.violation:
            raise ValueError("blocked evidence must be a violation")
        return self


class AuditEvent(_ClosedFrozen):
    event_id: UuidText
    event_type: AuditEventType
    occurred_at: datetime
    trace_id: UuidText | None = None
    run_id: UuidText | None = None
    subject_id: SubjectId | None = None
    resolved_role: Role | None = None
    mode: RagMode | None = None
    outcome: AuditOutcome
    corpus_version: str | None = None
    retrieved_document_count: int = Field(default=0, strict=True, ge=0, le=4)
    unauthorized_context_count: int = Field(default=0, strict=True, ge=0, le=4)
    canary_match_count: int = Field(default=0, strict=True, ge=0)
    protected_fragment_match_count: int = Field(default=0, strict=True, ge=0)
    detector_action: AuditDetectorAction = AuditDetectorAction.NONE
    retrieved_documents: tuple[RetrievedDocumentEvidence, ...] = Field(default=(), max_length=4)
    authorization_denials: tuple[AuthorizationDenial, ...] = Field(default=(), max_length=30)
    detections: tuple[DetectionEvidence, ...] = ()
    error_code: ErrorCode | None = None

    @field_validator("event_id", "trace_id", "run_id", mode="before")
    @classmethod
    def canonical_uuid(cls, value: Any) -> Any:
        return None if value is None else _uuid(value)

    @field_validator("occurred_at", mode="before")
    @classmethod
    def utc_timestamp(cls, value: Any) -> datetime:
        return _utc(value)

    @field_validator("corpus_version")
    @classmethod
    def fixed_corpus(cls, value: str | None) -> str | None:
        if value not in {None, SYNTHETIC_VERSION}:
            raise ValueError("corpus version is invalid")
        return value

    @model_validator(mode="after")
    def recompute_evidence_summary(self) -> Self:
        ranks = tuple(item.rank for item in self.retrieved_documents)
        ids = tuple(item.document_id for item in self.retrieved_documents)
        if ranks != tuple(range(1, len(ranks) + 1)) or len(ids) != len(set(ids)):
            raise ValueError("retrieved evidence must be unique and rank ordered")
        denial_ids = tuple(item.document_id for item in self.authorization_denials)
        if len(denial_ids) != len(set(denial_ids)):
            raise ValueError("authorization denials must be unique")
        detection_keys = tuple((item.type.value, item.evidence_id) for item in self.detections)
        if detection_keys != tuple(sorted(detection_keys)) or len(detection_keys) != len(set(detection_keys)):
            raise ValueError("detections must be unique and sorted")
        expected = {
            "retrieved_document_count": len(self.retrieved_documents),
            "unauthorized_context_count": sum(not item.authorized and item.included_in_context for item in self.retrieved_documents),
            "canary_match_count": sum(item.type in {DetectionType.DOCUMENT_CANARY, DetectionType.SYSTEM_CANARY} for item in self.detections),
            "protected_fragment_match_count": sum(item.type is DetectionType.UNAUTHORIZED_PROTECTED_FRAGMENT for item in self.detections),
            "detector_action": (AuditDetectorAction.BLOCKED if any(item.action is DetectionAction.BLOCKED for item in self.detections) else AuditDetectorAction.OBSERVED if self.detections else AuditDetectorAction.NONE),
        }
        for name, value in expected.items():
            if name in self.model_fields_set and getattr(self, name) != value:
                raise ValueError("audit evidence summary does not match children")
            object.__setattr__(self, name, value)
        return self


class AuditEventFilter(_ClosedFrozen):
    trace_id: UuidText | None = None
    run_id: UuidText | None = None
    subject_id: SubjectId | None = None
    mode: RagMode | None = None
    event_type: AuditEventType | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    cursor: str | None = Field(default=None, min_length=1, max_length=512, strict=True)
    limit: int = Field(default=50, strict=True, ge=1, le=200)

    @field_validator("trace_id", "run_id", mode="before")
    @classmethod
    def canonical_uuid(cls, value: Any) -> Any:
        return None if value is None else _uuid(value)

    @field_validator("start_time", "end_time", mode="before")
    @classmethod
    def utc_timestamp(cls, value: Any) -> Any:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def ordered_interval(self) -> Self:
        if self.start_time is not None and self.end_time is not None and self.start_time > self.end_time:
            raise ValueError("audit time interval is invalid")
        return self


class AuditEventPage(_ClosedFrozen):
    items: tuple[AuditEvent, ...] = Field(max_length=200)
    next_cursor: str | None = Field(default=None, max_length=512, strict=True)
