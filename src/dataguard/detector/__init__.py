"""Explicitly constructed deterministic whole-output detector.

Importing this package performs no resource, fixture, network, or filesystem I/O.
"""

from dataguard.detector.engine import (
    MAX_RAW_OUTPUT_BYTES,
    DetectorConfigurationError,
    DetectorInputError,
    WholeOutputDetector,
    build_whole_output_detector,
    normalize_detector_text,
)
from dataguard.detector.models import (
    DetectionAction,
    DetectionEvidence,
    DetectionType,
    DetectorMode,
    DetectorOutcome,
    DetectorResult,
)

__all__ = [
    "MAX_RAW_OUTPUT_BYTES",
    "DetectionAction",
    "DetectionEvidence",
    "DetectionType",
    "DetectorConfigurationError",
    "DetectorInputError",
    "DetectorMode",
    "DetectorOutcome",
    "DetectorResult",
    "WholeOutputDetector",
    "build_whole_output_detector",
    "normalize_detector_text",
]
