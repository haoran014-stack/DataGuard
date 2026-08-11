"""Closed minimized values for deterministic paired evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from dataguard.domain import Classification, Language, Role, ScenarioFamily
from dataguard.storage import AuthorizationDenial, DetectionEvidence, RetrievedDocumentEvidence


class EvaluationError(Exception):
    """A fixed content-free evaluation boundary failure."""

    __slots__ = ()
    _code = "internal_error"
    _message = "DataGuard could not complete the request."

    def __init__(self) -> None:
        super().__init__(self._message)

    @property
    def code(self) -> str: return self._code
    @property
    def message(self) -> str: return self._message
    def __setattr__(self, name: str, value: object) -> None:
        if name in {"__traceback__", "__cause__", "__context__", "__suppress_context__"}:
            return super().__setattr__(name, value)
        raise AttributeError("evaluation errors are fixed")
    def __str__(self) -> str: return self._message
    def __repr__(self) -> str: return "EvaluationError()"
    def as_dict(self) -> dict[str, str]: return {"code": self.code, "message": self.message}


class ModeOutcome(str, Enum):
    ANSWERED = "answered"
    BLOCKED = "blocked"
    FAILED = "failed"


class Judgment(str, Enum):
    ATTACK_SUCCEEDED = "attack_succeeded"
    ATTACK_PREVENTED = "attack_prevented"
    AUTHORIZED_QA_PASS = "authorized_qa_pass"
    AUTHORIZED_QA_FAIL = "authorized_qa_fail"
    FALSE_REJECTION = "false_rejection"
    INDETERMINATE = "indeterminate"


class PreventionStage(str, Enum):
    ROLE_FILTER = "role_filter"
    PROMPT_ISOLATION = "prompt_isolation"
    OUTPUT_GATE = "output_gate"


_MODE_TOKEN = object()
_SCENARIO_TOKEN = object()
_REPORT_TOKEN = object()


@dataclass(frozen=True, slots=True, repr=False, init=False)
class ModeEvidence:
    trace_id: str
    outcome: ModeOutcome
    judgment: Judgment
    retrieval_evidence: tuple[RetrievedDocumentEvidence, ...]
    authorization_denials: tuple[AuthorizationDenial, ...]
    detections: tuple[DetectionEvidence, ...]
    attack_delivered: bool
    final_leak_count: int
    fact_assertion_passed: bool | None
    latency_ms: int
    error_code: str | None

    def __init__(self, *, trace_id: str, outcome: ModeOutcome, judgment: Judgment,
                 retrieval_evidence: tuple[RetrievedDocumentEvidence, ...],
                 authorization_denials: tuple[AuthorizationDenial, ...],
                 detections: tuple[DetectionEvidence, ...], attack_delivered: bool,
                 final_leak_count: int, fact_assertion_passed: bool | None,
                 latency_ms: int, error_code: str | None, _token: object) -> None:
        if _token is not _MODE_TOKEN:
            raise EvaluationError()
        for name, value in locals().copy().items():
            if name not in {"self", "_token"}:
                object.__setattr__(self, name, value)

    def __repr__(self) -> str:
        return (f"ModeEvidence(outcome={self.outcome.value!r}, judgment={self.judgment.value!r}, "
                f"retrieved={len(self.retrieval_evidence)}, denials={len(self.authorization_denials)}, "
                f"detections={len(self.detections)})")

    def as_mapping(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id, "outcome": self.outcome.value,
            "judgment": self.judgment.value,
            "retrieval_evidence": [item.model_dump(mode="json") for item in self.retrieval_evidence],
            "authorization_denials": [item.model_dump(mode="json") for item in self.authorization_denials],
            "detections": [item.model_dump(mode="json") for item in self.detections],
            "attack_delivered": self.attack_delivered,
            "final_leak_count": self.final_leak_count,
            "fact_assertion_passed": self.fact_assertion_passed,
            "latency_ms": self.latency_ms, "error_code": self.error_code,
        }


@dataclass(frozen=True, slots=True, repr=False, init=False)
class ScenarioEvidence:
    scenario_id: str
    family: ScenarioFamily
    language: Language
    subject_id: str
    resolved_role: Role
    classification: Classification
    case_digest: str
    prevention_stage: PreventionStage | None
    baseline: ModeEvidence
    guarded: ModeEvidence
    _context_binding_digest: str
    _content_digest: str

    def __init__(self, *, scenario_id: str, family: ScenarioFamily, language: Language,
                 subject_id: str, resolved_role: Role, classification: Classification,
                 case_digest: str, prevention_stage: PreventionStage | None,
                 baseline: ModeEvidence, guarded: ModeEvidence,
                 context_binding_digest: str, _token: object) -> None:
        if _token is not _SCENARIO_TOKEN:
            raise EvaluationError()
        for name, value in locals().copy().items():
            if name not in {"self", "_token", "context_binding_digest"}:
                object.__setattr__(self, name, value)
        object.__setattr__(self, "_context_binding_digest", context_binding_digest)
        object.__setattr__(self, "_content_digest", _scenario_content_digest(self))

    def __repr__(self) -> str:
        return (f"ScenarioEvidence(family={self.family.value!r}, language={self.language.value!r}, "
                f"prevention_stage={None if self.prevention_stage is None else self.prevention_stage.value!r})")

    def as_mapping(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id, "family": self.family.value,
            "language": self.language.value, "subject_id": self.subject_id,
            "resolved_role": self.resolved_role.value,
            "classification": self.classification.value,
            "case_digest": self.case_digest,
            "prevention_stage": None if self.prevention_stage is None else self.prevention_stage.value,
            "baseline": self.baseline.as_mapping(), "guarded": self.guarded.as_mapping(),
        }


@dataclass(frozen=True, slots=True, repr=False, init=False)
class EvaluationReport:
    _canonical_bytes: bytes

    def __init__(self, mapping: dict[str, Any], canonical_bytes: bytes, *, _token: object) -> None:
        if _token is not _REPORT_TOKEN:
            raise EvaluationError()
        object.__setattr__(self, "_canonical_bytes", canonical_bytes)

    def as_mapping(self) -> dict[str, Any]:
        import json
        return json.loads(self._canonical_bytes)

    def canonical_bytes(self) -> bytes:
        return self._canonical_bytes

    def __repr__(self) -> str:
        return "EvaluationReport(schema_version='1.0', scenarios=62)"


def _mode_evidence(**values: Any) -> ModeEvidence:
    return ModeEvidence(**values, _token=_MODE_TOKEN)


def _scenario_evidence(**values: Any) -> ScenarioEvidence:
    return ScenarioEvidence(**values, _token=_SCENARIO_TOKEN)


def _scenario_content_digest(value: object) -> str | None:
    if type(value) is not ScenarioEvidence:
        return None
    import hashlib
    import json
    try:
        raw = json.dumps(value.as_mapping(), ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()
    except Exception:
        return None


def _evaluation_report(mapping: dict[str, Any], canonical_bytes: bytes) -> EvaluationReport:
    return EvaluationReport(mapping, canonical_bytes, _token=_REPORT_TOKEN)
