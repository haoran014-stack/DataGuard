"""Fixed public Problem Details catalog and content-safe exceptions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from uuid import UUID, uuid4

from .models import ProblemDetails


@dataclass(frozen=True, slots=True)
class ErrorDefinition:
    status: int
    retryable: bool
    title: str
    detail: str


ERROR_CATALOG: Final = {
    "invalid_request": ErrorDefinition(400, False, "Invalid request", "The request does not match the DataGuard API contract."),
    "subject_not_found": ErrorDefinition(404, False, "Synthetic subject not found", "The subject_id does not exist in the requested synthetic corpus version."),
    "corpus_not_found": ErrorDefinition(404, False, "Corpus not found", "The requested synthetic corpus version does not exist."),
    "scenario_set_not_found": ErrorDefinition(404, False, "Scenario set not found", "The requested synthetic scenario set version does not exist."),
    "run_not_found": ErrorDefinition(404, False, "Evaluation run not found", "The requested evaluation run does not exist."),
    "report_not_ready": ErrorDefinition(409, True, "Report not ready", "A report is available only when the evaluation run is completed."),
    "report_unavailable": ErrorDefinition(409, False, "Report unavailable", "The failed or interrupted evaluation run cannot produce a report."),
    "ollama_unavailable": ErrorDefinition(503, True, "Ollama unavailable", "The separately managed local Ollama runtime is unavailable."),
    "generation_model_unavailable": ErrorDefinition(503, True, "Generation model unavailable", "The required local qwen2.5:3b-instruct model is unavailable."),
    "embedding_model_unavailable": ErrorDefinition(503, True, "Embedding model unavailable", "The required local qwen3-embedding:0.6b model is unavailable."),
    "storage_unavailable": ErrorDefinition(503, True, "Storage unavailable", "The configured local experiment database is unavailable."),
    "model_timeout": ErrorDefinition(504, True, "Model timeout", "The local model did not finish within the configured timeout."),
    "model_protocol_error": ErrorDefinition(502, True, "Model protocol error", "The local model returned an invalid or incomplete response."),
    "experiment_manifest_mismatch": ErrorDefinition(409, False, "Experiment manifest mismatch", "The dataset, models, storage profile, or locked settings do not match the manifest."),
    "context_budget_exceeded": ErrorDefinition(422, False, "Context budget exceeded", "The question and retrieved context cannot fit the locked context budget."),
    "internal_error": ErrorDefinition(500, False, "Internal error", "DataGuard could not complete the request."),
}


class PublicProblem(Exception):
    __slots__ = ("_code", "_trace_id")

    def __init__(self, code: str, trace_id: str | None = None) -> None:
        self._code = code if code in ERROR_CATALOG else "internal_error"
        self._trace_id = _canonical_trace(trace_id) or str(uuid4())
        super().__init__(self._code)

    @property
    def code(self) -> str: return self._code
    @property
    def trace_id(self) -> str: return self._trace_id
    def __str__(self) -> str: return ERROR_CATALOG[self._code].detail
    def __repr__(self) -> str: return f"PublicProblem(code='{self._code}')"


def _canonical_trace(value: object) -> str | None:
    if type(value) is not str:
        return None
    try:
        return value if str(UUID(value)) == value else None
    except (ValueError, TypeError, AttributeError):
        return None


def problem_details(error: PublicProblem) -> ProblemDetails:
    definition = ERROR_CATALOG[error.code]
    return ProblemDetails(type=f"https://dataguard.local/problems/{error.code}",
        title=definition.title, status=definition.status, detail=definition.detail,
        code=error.code, trace_id=error.trace_id, retryable=definition.retryable)
