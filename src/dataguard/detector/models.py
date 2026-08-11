"""Closed minimized values emitted by the whole-output detector."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from dataguard.resources import FIXED_BLOCKED_REPLY


EvidenceId = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=128),
]


class DetectorMode(str, Enum):
    BASELINE = "baseline"
    GUARDED = "guarded"


class DetectionType(str, Enum):
    DOCUMENT_CANARY = "document_canary"
    SYSTEM_CANARY = "system_canary"
    UNAUTHORIZED_PROTECTED_FRAGMENT = "unauthorized_protected_fragment"


class DetectionAction(str, Enum):
    OBSERVED = "observed"
    BLOCKED = "blocked"


class DetectorOutcome(str, Enum):
    ANSWERED = "answered"
    BLOCKED = "blocked"


class _ClosedFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        hide_input_in_errors=True,
    )


class DetectionEvidence(_ClosedFrozenModel):
    type: DetectionType
    evidence_id: EvidenceId
    violation: bool = Field(strict=True)
    action: DetectionAction

    @model_validator(mode="after")
    def blocked_requires_violation(self) -> Self:
        if self.type in {
            DetectionType.DOCUMENT_CANARY,
            DetectionType.SYSTEM_CANARY,
        } and not self.violation:
            raise ValueError("Canary detector evidence must be a violation")
        if self.action is DetectionAction.BLOCKED and not self.violation:
            raise ValueError("blocked detector evidence must be a violation")
        return self


class DetectorResult(_ClosedFrozenModel):
    reply: str = Field(strict=True, repr=False)
    outcome: DetectorOutcome
    detections: tuple[DetectionEvidence, ...]

    @model_validator(mode="after")
    def require_closed_gate_semantics(self) -> Self:
        keys = tuple((item.type.value, item.evidence_id) for item in self.detections)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("detector evidence must be unique and sorted")
        if self.outcome is DetectorOutcome.BLOCKED:
            if self.reply != FIXED_BLOCKED_REPLY or not any(
                item.violation and item.action is DetectionAction.BLOCKED
                for item in self.detections
            ):
                raise ValueError("blocked detector result is invalid")
        elif any(item.action is DetectionAction.BLOCKED for item in self.detections):
            raise ValueError("answered detector result cannot contain a blocked action")
        return self
