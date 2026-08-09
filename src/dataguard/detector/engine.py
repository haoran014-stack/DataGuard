"""Deterministic, version-bound full-output detection and output gating."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import NoReturn

from dataguard.config import MAX_RESPONSE_BYTES
from dataguard.detector.models import (
    DetectionAction,
    DetectionEvidence,
    DetectionType,
    DetectorMode,
    DetectorOutcome,
    DetectorResult,
)
from dataguard.domain import Corpus, Role
from dataguard.resources import FIXED_BLOCKED_REPLY, SecurityResources
from dataguard.resources.loader import (
    DETECTION_TYPES,
    NORMALIZATION,
    ZERO_WIDTH_CODEPOINTS,
    DetectorResource,
    GuardPolicyResource,
    SystemPromptResource,
)


MAX_RAW_OUTPUT_BYTES = MAX_RESPONSE_BYTES
_ZERO_WIDTH_CHARACTERS = "\u200b\u200c\u200d\u2060\ufeff"
_ZERO_WIDTH_TRANSLATION = str.maketrans("", "", _ZERO_WIDTH_CHARACTERS)
_DETECTOR_FACTORY_TOKEN = object()


class DetectorInputError(ValueError):
    """Fixed input failure that never retains or echoes raw output."""

    def __init__(self) -> None:
        super().__init__("Detector input is invalid.")


class DetectorConfigurationError(ValueError):
    """Fixed factory failure that never retains or echoes marker values."""

    def __init__(self) -> None:
        super().__init__("Detector configuration is invalid.")


def _raise_input_error() -> NoReturn:
    raise DetectorInputError() from None


def _raise_configuration_error() -> NoReturn:
    raise DetectorConfigurationError() from None


def normalize_detector_text(value: str) -> str:
    """Apply the exact v1 normalization sequence to one complete string."""

    if type(value) is not str:
        _raise_input_error()
    try:
        if len(value.encode("utf-8")) > MAX_RAW_OUTPUT_BYTES:
            _raise_input_error()
    except UnicodeError:
        _raise_input_error()
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.casefold()
    normalized = normalized.translate(_ZERO_WIDTH_TRANSLATION)
    return " ".join(normalized.split())


@dataclass(frozen=True, slots=True, repr=False)
class _MarkerRule:
    type: DetectionType
    evidence_id: str
    normalized_marker: str
    source_allowed_roles: tuple[Role, ...] | None


class WholeOutputDetector:
    """Immutable marker set with one shared baseline/guarded evaluation path."""

    __slots__ = ("_fixed_reply", "_rules", "_sealed")

    def __init__(
        self,
        rules: tuple[_MarkerRule, ...],
        fixed_reply: str,
        *,
        _factory_token: object | None = None,
    ) -> None:
        if _factory_token is not _DETECTOR_FACTORY_TOKEN:
            _raise_configuration_error()
        if (
            type(rules) is not tuple
            or fixed_reply != FIXED_BLOCKED_REPLY
            or any(not isinstance(rule, _MarkerRule) for rule in rules)
        ):
            _raise_configuration_error()
        keys: set[tuple[DetectionType, str]] = set()
        evidence_ids: set[str] = set()
        for rule in rules:
            key = (rule.type, rule.evidence_id)
            allowed_roles_valid = (
                rule.source_allowed_roles is None
                if rule.type in {
                    DetectionType.DOCUMENT_CANARY,
                    DetectionType.SYSTEM_CANARY,
                }
                else type(rule.source_allowed_roles) is tuple
                and bool(rule.source_allowed_roles)
                and len(rule.source_allowed_roles) == len(set(rule.source_allowed_roles))
                and all(isinstance(role, Role) for role in rule.source_allowed_roles)
            )
            if (
                type(rule.evidence_id) is not str
                or not 1 <= len(rule.evidence_id) <= 128
                or type(rule.normalized_marker) is not str
                or not rule.normalized_marker
                or key in keys
                or rule.evidence_id in evidence_ids
                or not allowed_roles_valid
            ):
                _raise_configuration_error()
            keys.add(key)
            evidence_ids.add(rule.evidence_id)
        object.__setattr__(self, "_rules", rules)
        object.__setattr__(self, "_fixed_reply", fixed_reply)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("WholeOutputDetector is immutable")
        object.__setattr__(self, name, value)

    def __repr__(self) -> str:
        return f"WholeOutputDetector(marker_count={len(self._rules)})"

    @property
    def marker_count(self) -> int:
        return len(self._rules)

    def evaluate(
        self,
        raw_output: str,
        *,
        role: Role,
        mode: DetectorMode,
    ) -> DetectorResult:
        """Scan the complete output once, then apply the selected mode gate."""

        if not isinstance(role, Role) or not isinstance(mode, DetectorMode):
            _raise_input_error()
        normalized_output = normalize_detector_text(raw_output)
        evidence: list[DetectionEvidence] = []
        for rule in self._rules:
            if rule.normalized_marker not in normalized_output:
                continue
            violation = (
                rule.type is not DetectionType.UNAUTHORIZED_PROTECTED_FRAGMENT
                or rule.source_allowed_roles is None
                or role not in rule.source_allowed_roles
            )
            action = (
                DetectionAction.BLOCKED
                if mode is DetectorMode.GUARDED and violation
                else DetectionAction.OBSERVED
            )
            evidence.append(
                DetectionEvidence(
                    type=rule.type,
                    evidence_id=rule.evidence_id,
                    violation=violation,
                    action=action,
                )
            )

        detections = tuple(
            sorted(evidence, key=lambda item: (item.type.value, item.evidence_id))
        )
        must_block = mode is DetectorMode.GUARDED and any(
            item.violation for item in detections
        )
        if must_block:
            return DetectorResult(
                reply=self._fixed_reply,
                outcome=DetectorOutcome.BLOCKED,
                detections=detections,
            )
        return DetectorResult(
            reply=raw_output,
            outcome=DetectorOutcome.ANSWERED,
            detections=detections,
        )


def build_whole_output_detector(
    resources: SecurityResources,
    corpus: Corpus,
) -> WholeOutputDetector:
    """Explicitly bind reviewed resources and an already loaded synthetic corpus."""

    if not isinstance(resources, SecurityResources) or not isinstance(corpus, Corpus):
        _raise_configuration_error()
    system_prompt = resources.system_prompt.value
    detector = resources.detector.value
    policy = resources.guard_policy.value
    if (
        not isinstance(system_prompt, SystemPromptResource)
        or not isinstance(detector, DetectorResource)
        or not isinstance(policy, GuardPolicyResource)
        or detector.scan_scope != "full_output_untruncated"
        or detector.normalization != NORMALIZATION
        or detector.zero_width_codepoints != ZERO_WIDTH_CODEPOINTS
        or detector.detection_types != DETECTION_TYPES
        or detector.baseline_action != "observed"
        or detector.guarded_action != "blocked"
        or detector.raw_output_persistence != "forbidden"
        or detector.guarded_fixed_reply != FIXED_BLOCKED_REPLY
        or detector.guarded_fixed_reply != policy.guarded_fixed_reply
    ):
        _raise_configuration_error()

    candidates: list[
        tuple[DetectionType, str, str, tuple[Role, ...] | None]
    ] = [
        (
            DetectionType.SYSTEM_CANARY,
            str(system_prompt.system_canary_evidence_id),
            system_prompt.system_canary_literal,
            None,
        )
    ]
    for document in corpus.documents:
        if any(
            fragment.allowed_roles != document.allowed_roles
            for fragment in document.protected_fragments
        ):
            _raise_configuration_error()
        candidates.extend(
            (
                DetectionType.DOCUMENT_CANARY,
                canary.canary_id,
                canary.value,
                None,
            )
            for canary in document.canaries
        )
        candidates.extend(
            (
                DetectionType.UNAUTHORIZED_PROTECTED_FRAGMENT,
                fragment.fragment_id,
                fragment.value,
                document.allowed_roles,
            )
            for fragment in document.protected_fragments
        )

    rules: list[_MarkerRule] = []
    evidence_ids: set[str] = set()
    for detection_type, evidence_id, marker, source_allowed_roles in candidates:
        if evidence_id in evidence_ids:
            _raise_configuration_error()
        evidence_ids.add(evidence_id)
        try:
            normalized_marker = normalize_detector_text(marker)
        except DetectorInputError:
            _raise_configuration_error()
        if not normalized_marker:
            _raise_configuration_error()
        rules.append(
            _MarkerRule(
                type=detection_type,
                evidence_id=evidence_id,
                normalized_marker=normalized_marker,
                source_allowed_roles=source_allowed_roles,
            )
        )

    return WholeOutputDetector(
        tuple(rules),
        detector.guarded_fixed_reply,
        _factory_token=_DETECTOR_FACTORY_TOKEN,
    )
