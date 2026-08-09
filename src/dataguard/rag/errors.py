"""Content-free failures for Stage 2 RAG planning."""

from __future__ import annotations

from enum import Enum
from typing import NoReturn


class RagPlanningErrorCode(str, Enum):
    INVALID_REQUEST = "invalid_request"
    SUBJECT_NOT_FOUND = "subject_not_found"
    CORPUS_NOT_FOUND = "corpus_not_found"
    EXPERIMENT_MANIFEST_MISMATCH = "experiment_manifest_mismatch"
    CONTEXT_BUDGET_EXCEEDED = "context_budget_exceeded"


_MESSAGES = {
    RagPlanningErrorCode.INVALID_REQUEST: "The request does not match the DataGuard contract.",
    RagPlanningErrorCode.SUBJECT_NOT_FOUND: "The synthetic subject is unavailable.",
    RagPlanningErrorCode.CORPUS_NOT_FOUND: "The synthetic corpus is unavailable.",
    RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH: (
        "The experiment resources do not match the accepted manifest."
    ),
    RagPlanningErrorCode.CONTEXT_BUDGET_EXCEEDED: (
        "The request does not fit the locked context budget."
    ),
}


class RagPlanningError(Exception):
    """Stable planning error that never includes caller or corpus content."""

    def __init__(self, code: RagPlanningErrorCode) -> None:
        self.code = code
        self.message = _MESSAGES[code]
        super().__init__(self.message)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "message": self.message}


def raise_rag_error(code: RagPlanningErrorCode) -> NoReturn:
    raise RagPlanningError(code)
