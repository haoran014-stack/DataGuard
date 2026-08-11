"""Closed minimized values produced by Stage 2 RAG planning."""

from __future__ import annotations

import hashlib
import json
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


@dataclass(frozen=True, slots=True, repr=False)
class PlannerBindingFacts:
    """Stable vector-free facts shared by both members of a planned pair."""

    corpus_sha256: str
    resource_digests: tuple[tuple[str, str], ...]
    index_binding_digest: str
    embedding_model_tag: str
    embedding_model_digest: str
    dimensions: int

    def __repr__(self) -> str:
        return "PlannerBindingFacts()"


@dataclass(frozen=True, slots=True, repr=False)
class RequestBindingFacts:
    """Stable request facts without retaining or rendering the raw question."""

    corpus_version: str
    subject_id: str
    question_sha256: str

    def __repr__(self) -> str:
        return "RequestBindingFacts()"


@dataclass(frozen=True, slots=True, repr=False, init=False)
class RagPlan:
    """Immutable plan whose repr intentionally omits every message body."""

    mode: RagMode
    resolved_role: Role
    retrieval_results: tuple[RetrievalResult, ...]
    authorization_denials: tuple[AuthorizationDenial, ...]
    messages: tuple[OllamaMessage, ...]
    context_message_bytes: int
    _session_identity: object
    _plan_identity: object
    _paired: bool
    _binding_facts: PlannerBindingFacts | None
    _integrity_digest: str

    def __init__(
        self,
        *,
        mode: RagMode,
        resolved_role: Role,
        retrieval_results: tuple[RetrievalResult, ...],
        authorization_denials: tuple[AuthorizationDenial, ...],
        messages: tuple[OllamaMessage, ...],
        context_message_bytes: int,
        session_identity: object,
        plan_identity: object,
        paired: bool,
        binding_facts: PlannerBindingFacts | None,
        integrity_digest: str,
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
        object.__setattr__(self, "_session_identity", session_identity)
        object.__setattr__(self, "_plan_identity", plan_identity)
        object.__setattr__(self, "_paired", paired)
        object.__setattr__(self, "_binding_facts", binding_facts)
        object.__setattr__(self, "_integrity_digest", integrity_digest)

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
    session_identity: object | None = None,
    plan_identity: object | None = None,
    paired: bool = False,
    binding_facts: PlannerBindingFacts | None = None,
) -> RagPlan:
    accepted_session = object() if session_identity is None else session_identity
    accepted_plan = object() if plan_identity is None else plan_identity
    integrity_digest = _plan_integrity_digest(
        mode, resolved_role, retrieval_results, authorization_denials,
        messages, context_message_bytes,
    )
    return RagPlan(
        mode=mode,
        resolved_role=resolved_role,
        retrieval_results=retrieval_results,
        authorization_denials=authorization_denials,
        messages=messages,
        context_message_bytes=context_message_bytes,
        session_identity=accepted_session,
        plan_identity=accepted_plan,
        paired=paired,
        binding_facts=binding_facts,
        integrity_digest=integrity_digest,
        _token=_PLAN_TOKEN,
    )


def _plan_integrity_digest(
    mode: RagMode, role: Role, retrieval_results: tuple[RetrievalResult, ...],
    authorization_denials: tuple[AuthorizationDenial, ...],
    messages: tuple[OllamaMessage, ...], context_message_bytes: int,
) -> str:
    payload = {
        "mode": mode.value, "resolved_role": role.value,
        "retrieval_results": [item.model_dump(mode="json") for item in retrieval_results],
        "authorization_denials": [item.model_dump(mode="json") for item in authorization_denials],
        "messages": [item.model_dump(mode="json") for item in messages],
        "context_message_bytes": context_message_bytes,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _rag_plan_integrity(value: object) -> str | None:
    if type(value) is not RagPlan:
        return None
    try:
        return _plan_integrity_digest(value.mode, value.resolved_role,
            value.retrieval_results, value.authorization_denials,
            value.messages, value.context_message_bytes)
    except Exception:
        return None
