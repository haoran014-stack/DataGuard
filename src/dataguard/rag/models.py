"""Closed minimized values produced by Stage 2 RAG planning."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from dataguard.domain import Role
from dataguard.ollama import OllamaMessage
from dataguard.vector_index import RetrievalResult


class RagMode(str, Enum):
    BASELINE = "baseline"
    GUARDED = "guarded"


class AuthorizationDenial(BaseModel):
    """Structured pre-retrieval denial without document content."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        hide_input_in_errors=True,
    )

    doc_id: Annotated[
        str,
        StringConstraints(strict=True, min_length=1, max_length=128),
    ]
    reason: Literal["role_not_allowed"]


_PLAN_TOKEN = object()


@dataclass(frozen=True, slots=True, repr=False, init=False)
class RagPlan:
    """Immutable plan whose repr intentionally omits every message body."""

    mode: RagMode
    resolved_role: Role
    retrieval_results: tuple[RetrievalResult, ...]
    authorization_denials: tuple[AuthorizationDenial, ...]
    messages: tuple[OllamaMessage, ...]
    context_message_bytes: int

    def __init__(
        self,
        *,
        mode: RagMode,
        resolved_role: Role,
        retrieval_results: tuple[RetrievalResult, ...],
        authorization_denials: tuple[AuthorizationDenial, ...],
        messages: tuple[OllamaMessage, ...],
        context_message_bytes: int,
        _token: object,
    ) -> None:
        if _token is not _PLAN_TOKEN:
            raise TypeError("RAG plans are created only by the validated planner")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "resolved_role", resolved_role)
        object.__setattr__(self, "retrieval_results", retrieval_results)
        object.__setattr__(self, "authorization_denials", authorization_denials)
        object.__setattr__(self, "messages", messages)
        object.__setattr__(self, "context_message_bytes", context_message_bytes)

    def __repr__(self) -> str:
        return (
            "RagPlan("
            f"mode={self.mode.value!r}, resolved_role={self.resolved_role.value!r}, "
            f"retrieved={len(self.retrieval_results)}, "
            f"denials={len(self.authorization_denials)}, "
            f"messages={len(self.messages)}, "
            f"context_message_bytes={self.context_message_bytes})"
        )


def _create_rag_plan(
    *,
    mode: RagMode,
    resolved_role: Role,
    retrieval_results: tuple[RetrievalResult, ...],
    authorization_denials: tuple[AuthorizationDenial, ...],
    messages: tuple[OllamaMessage, ...],
    context_message_bytes: int,
) -> RagPlan:
    return RagPlan(
        mode=mode,
        resolved_role=resolved_role,
        retrieval_results=retrieval_results,
        authorization_denials=authorization_denials,
        messages=messages,
        context_message_bytes=context_message_bytes,
        _token=_PLAN_TOKEN,
    )
