"""Generation and whole-output detector orchestration for validated RAG plans."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import NoReturn

from pydantic import ValidationError

from dataguard.detector import (
    DetectionAction,
    DetectionEvidence,
    DetectorMode,
    DetectorOutcome,
    DetectorResult,
    WholeOutputDetector,
)
from dataguard.domain import Role
from dataguard.ollama import OllamaClient, OllamaMessage
from dataguard.rag.errors import RagPlanningError
from dataguard.rag.models import AuthorizationDenial, RagMode, RagPlan, _rag_plan_integrity
from dataguard.rag.planner import NUM_CTX, NUM_PREDICT, context_message_bytes
from dataguard.resources import FIXED_BLOCKED_REPLY
from dataguard.vector_index import RetrievalResult


class RagExecutionErrorCode(str, Enum):
    INTERNAL_ERROR = "internal_error"


class RagExecutionError(Exception):
    """Fixed internal failure that never includes plan, output, or detector content."""

    __slots__ = ("code", "message")

    def __init__(self) -> None:
        self.code = RagExecutionErrorCode.INTERNAL_ERROR
        self.message = "DataGuard could not complete the request."
        super().__init__(self.message)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "message": self.message}


def _raise_internal_error() -> NoReturn:
    raise RagExecutionError() from None


_RESULT_TOKEN = object()
_EXECUTOR_TOKEN = object()


@dataclass(frozen=True, slots=True, repr=False, init=False)
class RagExecutionResult:
    """Final in-memory response and minimized detector evidence."""

    reply: str
    outcome: DetectorOutcome
    detections: tuple[DetectionEvidence, ...]
    _session_identity: object
    _plan_identity: object
    _mode: RagMode
    _plan_integrity_digest: str

    def __init__(
        self,
        *,
        reply: str,
        outcome: DetectorOutcome,
        detections: tuple[DetectionEvidence, ...],
        session_identity: object | None = None,
        plan_identity: object | None = None,
        mode: RagMode = RagMode.BASELINE,
        plan_integrity_digest: str | None = None,
        _token: object,
    ) -> None:
        if (_token is not _RESULT_TOKEN or session_identity is None
                or plan_identity is None or type(mode) is not RagMode
                or type(plan_integrity_digest) is not str):
            _raise_internal_error()
        object.__setattr__(self, "reply", reply)
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(self, "detections", detections)
        object.__setattr__(self, "_session_identity", session_identity)
        object.__setattr__(self, "_plan_identity", plan_identity)
        object.__setattr__(self, "_mode", mode)
        object.__setattr__(self, "_plan_integrity_digest", plan_integrity_digest)

    def __repr__(self) -> str:
        return (
            "RagExecutionResult("
            f"outcome={self.outcome.value!r}, detections={len(self.detections)})"
        )


@dataclass(frozen=True, slots=True)
class _ValidatedPlan:
    mode: RagMode
    role: Role
    messages: tuple[OllamaMessage, ...]
    session_identity: object
    plan_identity: object
    paired: bool
    integrity_digest: str


def _validate_plan(plan: object) -> _ValidatedPlan:
    if type(plan) is not RagPlan:
        _raise_internal_error()
    try:
        if type(plan.mode) is not RagMode or type(plan.resolved_role) is not Role:
            raise ValueError
        if type(plan.retrieval_results) is not tuple or len(plan.retrieval_results) != 4:
            raise ValueError
        retrieval_results = tuple(
            RetrievalResult.model_validate(
                result.model_dump(mode="python", warnings=False)
            )
            for result in plan.retrieval_results
            if type(result) is RetrievalResult
        )
        if len(retrieval_results) != 4:
            raise ValueError
        retrieval_ids = tuple(result.doc_id for result in retrieval_results)
        if len(set(retrieval_ids)) != 4:
            raise ValueError

        if type(plan.authorization_denials) is not tuple:
            raise ValueError
        denials = tuple(
            AuthorizationDenial.model_validate(
                denial.model_dump(mode="python", warnings=False)
            )
            for denial in plan.authorization_denials
            if type(denial) is AuthorizationDenial
        )
        if len(denials) != len(plan.authorization_denials):
            raise ValueError
        denial_ids = tuple(denial.doc_id for denial in denials)
        if len(set(denial_ids)) != len(denial_ids) or set(denial_ids) & set(retrieval_ids):
            raise ValueError

        if type(plan.messages) is not tuple:
            raise ValueError
        messages = tuple(
            OllamaMessage.model_validate(
                message.model_dump(mode="python", warnings=False)
            )
            for message in plan.messages
            if type(message) is OllamaMessage
        )
        if len(messages) != len(plan.messages):
            raise ValueError
        expected_roles = (
            ("user",)
            if plan.mode is RagMode.BASELINE
            else ("system", "user", "user")
        )
        if tuple(message.role for message in messages) != expected_roles:
            raise ValueError
        expected_denials = (
            0
            if plan.mode is RagMode.BASELINE
            else {
                Role.GUEST: 20,
                Role.EMPLOYEE: 10,
                Role.SECURITY_REVIEWER: 0,
            }[plan.resolved_role]
        )
        if len(denials) != expected_denials:
            raise ValueError
        if (
            type(plan.context_message_bytes) is not int
            or plan.context_message_bytes != context_message_bytes(messages)
            or plan.context_message_bytes + NUM_PREDICT > NUM_CTX
        ):
            raise ValueError
    except (AttributeError, TypeError, ValueError, ValidationError, RagPlanningError):
        _raise_internal_error()
    actual_integrity = _rag_plan_integrity(plan)
    if (plan._session_identity is None or plan._plan_identity is None
            or type(plan._paired) is not bool or actual_integrity is None
            or actual_integrity != plan._integrity_digest):
        _raise_internal_error()
    return _ValidatedPlan(mode=plan.mode, role=plan.resolved_role, messages=messages,
                          session_identity=plan._session_identity,
                          plan_identity=plan._plan_identity, paired=plan._paired,
                          integrity_digest=actual_integrity)


def _execution_result_binding(value: object) -> tuple[object, object, RagMode, str] | None:
    if type(value) is not RagExecutionResult:
        return None
    return (value._session_identity, value._plan_identity, value._mode,
            value._plan_integrity_digest)


def _validated_detector_result(value: object) -> DetectorResult | None:
    if type(value) is not DetectorResult:
        return None
    try:
        return DetectorResult.model_validate(
            value.model_dump(mode="python", warnings=False)
        )
    except (AttributeError, TypeError, ValueError, ValidationError):
        return None


def _result_matches_execution(
    result: DetectorResult,
    *,
    mode: RagMode,
    raw_output: str,
) -> bool:
    if mode is RagMode.BASELINE:
        return (
            result.outcome is DetectorOutcome.ANSWERED
            and result.reply == raw_output
            and all(
                detection.action is DetectionAction.OBSERVED
                for detection in result.detections
            )
        )

    has_violation = any(detection.violation for detection in result.detections)
    actions_match = all(
        detection.action
        is (
            DetectionAction.BLOCKED
            if detection.violation
            else DetectionAction.OBSERVED
        )
        for detection in result.detections
    )
    if not actions_match:
        return False
    if has_violation:
        return (
            result.outcome is DetectorOutcome.BLOCKED
            and result.reply == FIXED_BLOCKED_REPLY
        )
    return result.outcome is DetectorOutcome.ANSWERED and result.reply == raw_output


@dataclass(frozen=True, slots=True, repr=False, init=False)
class RagExecutor:
    """Call generation once, then the shared whole-output detector once."""

    _client: OllamaClient
    _detector: WholeOutputDetector

    def __init__(
        self,
        client: OllamaClient,
        detector: WholeOutputDetector,
        *,
        _token: object,
    ) -> None:
        if _token is not _EXECUTOR_TOKEN:
            _raise_internal_error()
        object.__setattr__(self, "_client", client)
        object.__setattr__(self, "_detector", detector)

    def __repr__(self) -> str:
        return "RagExecutor(local_generation=True, whole_output_detector=True)"

    async def execute(self, plan: RagPlan) -> RagExecutionResult:
        validated = _validate_plan(plan)

        # OllamaAdapterError intentionally propagates unchanged for later API mapping.
        raw_output = await self._client.chat(validated.messages)
        try:
            detector_result = self._detector.evaluate(
                raw_output,
                role=validated.role,
                mode=(
                    DetectorMode.BASELINE
                    if validated.mode is RagMode.BASELINE
                    else DetectorMode.GUARDED
                ),
            )
        except Exception:
            raw_output = ""
            _raise_internal_error()

        safe_result = _validated_detector_result(detector_result)
        if safe_result is None or not _result_matches_execution(
            safe_result,
            mode=validated.mode,
            raw_output=raw_output,
        ):
            detector_result = None
            safe_result = None
            raw_output = ""
            _raise_internal_error()
        if safe_result.outcome is DetectorOutcome.BLOCKED:
            raw_output = ""
        return RagExecutionResult(
            reply=safe_result.reply,
            outcome=safe_result.outcome,
            detections=safe_result.detections,
            session_identity=validated.session_identity,
            plan_identity=validated.plan_identity,
            mode=validated.mode,
            plan_integrity_digest=validated.integrity_digest,
            _token=_RESULT_TOKEN,
        )


def create_rag_executor(
    client: OllamaClient,
    detector: WholeOutputDetector,
) -> RagExecutor:
    """Bind the real local adapter and controlled detector without performing I/O."""

    try:
        if type(client) is not OllamaClient or type(detector) is not WholeOutputDetector:
            raise ValueError
        if type(detector.marker_count) is not int or detector.marker_count <= 0:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        _raise_internal_error()
    return RagExecutor(client, detector, _token=_EXECUTOR_TOKEN)
