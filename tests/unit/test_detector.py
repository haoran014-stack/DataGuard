from __future__ import annotations

import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from dataguard.config import MAX_RESPONSE_BYTES
from dataguard.detector import (
    MAX_RAW_OUTPUT_BYTES,
    DetectionAction,
    DetectionEvidence,
    DetectionType,
    DetectorConfigurationError,
    DetectorInputError,
    DetectorMode,
    DetectorOutcome,
    DetectorResult,
    WholeOutputDetector,
    build_whole_output_detector,
    normalize_detector_text,
)
from dataguard.domain import Canary, Corpus, ProtectedFragment, Role
from dataguard.resources import FIXED_BLOCKED_REPLY, SecurityResources, load_security_resources
from dataguard.validation import FixtureBundle, load_fixture_bundle


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_SENTINEL = "RAW_OUTPUT_SENTINEL_SHOULD_NOT_APPEAR"


@lru_cache(maxsize=1)
def _loaded() -> tuple[WholeOutputDetector, SecurityResources, FixtureBundle]:
    resource_set = load_security_resources()
    bundle_result = load_fixture_bundle(PROJECT_ROOT)
    if bundle_result.bundle is None:
        pytest.fail("accepted fixture bundle did not load")
    return (
        build_whole_output_detector(resource_set, bundle_result.bundle.corpus),
        resource_set,
        bundle_result.bundle,
    )


def _system_marker(resources: SecurityResources) -> str:
    return resources.system_prompt.value.system_canary_literal  # type: ignore[union-attr]


def _system_evidence_id(resources: SecurityResources) -> str:
    return str(resources.system_prompt.value.system_canary_evidence_id)  # type: ignore[union-attr]


def _first_canary(bundle: FixtureBundle) -> Canary:
    return bundle.corpus.documents[0].canaries[0]


def _fragment_with_roles(
    bundle: FixtureBundle,
    allowed_roles: tuple[Role, ...],
) -> ProtectedFragment:
    return next(
        fragment
        for document in bundle.corpus.documents
        for fragment in document.protected_fragments
        if fragment.allowed_roles == allowed_roles
    )


def _fullwidth_ascii(value: str) -> str:
    return "".join(
        chr(ord(character) + 0xFEE0)
        if 0x21 <= ord(character) <= 0x7E
        else character
        for character in value
    )


def _detection(result: DetectorResult, evidence_id: str) -> DetectionEvidence:
    return next(item for item in result.detections if item.evidence_id == evidence_id)


def _assert_content_free_error(error: BaseException) -> None:
    rendered = str(error) + repr(error)
    assert RAW_SENTINEL not in rendered
    assert "DG_" not in rendered
    assert len(rendered) < 1024


def test_factory_uses_only_loaded_resources_and_corpus_without_exposing_markers() -> None:
    detector, resources, bundle = _loaded()

    assert detector.marker_count == 1 + sum(
        len(document.canaries) + len(document.protected_fragments)
        for document in bundle.corpus.documents
    )
    rendered = repr(detector)
    assert _system_marker(resources) not in rendered
    assert _first_canary(bundle).value not in rendered
    assert "marker_count=" in rendered


def test_nfkc_compatibility_and_casefold_match_the_same_document_canary() -> None:
    detector, _, bundle = _loaded()
    canary = _first_canary(bundle)

    for variant in (_fullwidth_ascii(canary.value), canary.value.swapcase()):
        result = detector.evaluate(
            variant,
            role=Role.GUEST,
            mode=DetectorMode.BASELINE,
        )
        evidence = _detection(result, canary.canary_id)
        assert evidence.violation is True
        assert evidence.action is DetectionAction.OBSERVED


@pytest.mark.parametrize("zero_width", ["\u200b", "\u200c", "\u200d", "\u2060", "\ufeff"])
def test_each_locked_zero_width_character_is_removed(zero_width: str) -> None:
    detector, _, bundle = _loaded()
    canary = _first_canary(bundle)
    midpoint = len(canary.value) // 2
    variant = canary.value[:midpoint] + zero_width + canary.value[midpoint:]

    result = detector.evaluate(variant, role=Role.GUEST, mode=DetectorMode.BASELINE)
    assert _detection(result, canary.canary_id).violation is True


def test_all_locked_zero_width_characters_are_removed_in_one_output() -> None:
    detector, _, bundle = _loaded()
    canary = _first_canary(bundle)
    characters = ("\u200b", "\u200c", "\u200d", "\u2060", "\ufeff")
    variant = "".join(
        character + characters[index % len(characters)]
        for index, character in enumerate(canary.value)
    )

    result = detector.evaluate(variant, role=Role.EMPLOYEE, mode=DetectorMode.BASELINE)
    assert _detection(result, canary.canary_id).violation is True


def test_unlisted_format_character_is_not_deleted() -> None:
    detector, _, bundle = _loaded()
    canary = _first_canary(bundle)
    midpoint = len(canary.value) // 2
    variant = canary.value[:midpoint] + "\u200e" + canary.value[midpoint:]

    result = detector.evaluate(variant, role=Role.GUEST, mode=DetectorMode.BASELINE)
    assert all(item.evidence_id != canary.canary_id for item in result.detections)


def test_unicode_whitespace_runs_collapse_for_protected_fragment_matching() -> None:
    _, resources, bundle = _loaded()
    documents = list(bundle.corpus.documents)
    source = documents[0]
    fragment = source.protected_fragments[0].model_copy(
        update={"value": "SYNTHETIC WHITESPACE FRAGMENT"}
    )
    documents[0] = source.model_copy(update={"protected_fragments": (fragment,)})
    corpus = bundle.corpus.model_copy(update={"documents": tuple(documents)})
    detector = build_whole_output_detector(resources, corpus)
    variant = fragment.value.replace(" ", "\u00a0\u2003\t\n\u3000")

    result = detector.evaluate(variant, role=Role.GUEST, mode=DetectorMode.BASELINE)
    assert _detection(result, fragment.fragment_id).action is DetectionAction.OBSERVED


def test_normalization_collapses_unicode_whitespace_and_trims_both_ends() -> None:
    value = "\u3000Straße\u00a0\u2003\tＦＯＯ\n"
    assert normalize_detector_text(value) == "strasse foo"


@pytest.mark.parametrize("position", ["start", "middle", "end"])
def test_marker_at_start_middle_and_end_is_detected(position: str) -> None:
    detector, _, bundle = _loaded()
    canary = _first_canary(bundle)
    raw = {
        "start": canary.value + " synthetic suffix",
        "middle": "synthetic prefix " + canary.value + " synthetic suffix",
        "end": "synthetic prefix " + canary.value,
    }[position]

    result = detector.evaluate(raw, role=Role.GUEST, mode=DetectorMode.BASELINE)
    assert _detection(result, canary.canary_id).violation is True


def test_long_output_tail_is_scanned_without_truncation() -> None:
    detector, _, bundle = _loaded()
    canary = _first_canary(bundle)
    raw = ("synthetic filler " * 80_000) + canary.value

    result = detector.evaluate(raw, role=Role.GUEST, mode=DetectorMode.BASELINE)
    assert result.reply == raw
    assert _detection(result, canary.canary_id).violation is True


def test_multiple_markers_repetition_stable_sort_and_unique_evidence() -> None:
    detector, resources, bundle = _loaded()
    canary = _first_canary(bundle)
    fragment = bundle.corpus.documents[0].protected_fragments[0]
    raw = " | ".join(
        (
            fragment.value,
            _system_marker(resources),
            canary.value,
            canary.value,
        )
    )

    first = detector.evaluate(raw, role=Role.GUEST, mode=DetectorMode.BASELINE)
    second = detector.evaluate(raw, role=Role.GUEST, mode=DetectorMode.BASELINE)
    keys = tuple((item.type.value, item.evidence_id) for item in first.detections)
    assert first == second
    assert keys == tuple(sorted(keys))
    assert len(keys) == len(set(keys))
    assert sum(item.evidence_id == canary.canary_id for item in first.detections) == 1


def test_normalization_collision_preserves_each_distinct_evidence_id() -> None:
    _, resources, bundle = _loaded()
    documents = list(bundle.corpus.documents)
    collision = "Synthetic Collision Marker 42"
    first_canary = documents[0].canaries[0].model_copy(update={"value": collision})
    second_canary = documents[1].canaries[0].model_copy(
        update={"value": _fullwidth_ascii(collision.swapcase())}
    )
    documents[0] = documents[0].model_copy(update={"canaries": (first_canary,)})
    documents[1] = documents[1].model_copy(update={"canaries": (second_canary,)})
    corpus = bundle.corpus.model_copy(update={"documents": tuple(documents)})
    detector = build_whole_output_detector(resources, corpus)

    result = detector.evaluate(collision, role=Role.GUEST, mode=DetectorMode.BASELINE)
    collision_ids = {first_canary.canary_id, second_canary.canary_id}
    assert {item.evidence_id for item in result.detections} >= collision_ids


def test_all_system_and_document_canaries_are_violations_for_every_role() -> None:
    detector, resources, bundle = _loaded()
    canary = _first_canary(bundle)
    raw = _system_marker(resources) + " " + canary.value
    expected_ids = {_system_evidence_id(resources), canary.canary_id}

    for role in Role:
        result = detector.evaluate(raw, role=role, mode=DetectorMode.BASELINE)
        matching = [item for item in result.detections if item.evidence_id in expected_ids]
        assert len(matching) == 2
        assert all(item.violation for item in matching)
        assert all(item.action is DetectionAction.OBSERVED for item in matching)


def test_protected_fragment_uses_source_document_roles_for_all_roles() -> None:
    detector, _, bundle = _loaded()
    for document in bundle.corpus.documents:
        for fragment in document.protected_fragments:
            assert fragment.allowed_roles == document.allowed_roles
            for role in Role:
                result = detector.evaluate(
                    fragment.value,
                    role=role,
                    mode=DetectorMode.BASELINE,
                )
                evidence = _detection(result, fragment.fragment_id)
                assert evidence.violation is (role not in document.allowed_roles)
                assert evidence.action is DetectionAction.OBSERVED


def test_role_matrix_covers_public_internal_and_confidential_source_documents() -> None:
    detector, _, bundle = _loaded()
    source_cases = (
        (Role.GUEST, Role.EMPLOYEE, Role.SECURITY_REVIEWER),
        (Role.EMPLOYEE, Role.SECURITY_REVIEWER),
        (Role.SECURITY_REVIEWER,),
    )
    for allowed_roles in source_cases:
        document = next(
            item for item in bundle.corpus.documents if item.allowed_roles == allowed_roles
        )
        fragment = document.protected_fragments[0]
        for role in Role:
            result = detector.evaluate(
                fragment.value,
                role=role,
                mode=DetectorMode.BASELINE,
            )
            evidence = _detection(result, fragment.fragment_id)
            assert evidence.violation is (role not in document.allowed_roles)
            assert evidence.action is DetectionAction.OBSERVED


def test_factory_rejects_fragment_roles_that_differ_from_source_document() -> None:
    _, resources, bundle = _loaded()
    documents = list(bundle.corpus.documents)
    source = documents[0]
    fragment = source.protected_fragments[0].model_copy(
        update={"allowed_roles": (Role.SECURITY_REVIEWER,)}
    )
    documents[0] = source.model_copy(update={"protected_fragments": (fragment,)})
    corpus = bundle.corpus.model_copy(update={"documents": tuple(documents)})

    with pytest.raises(DetectorConfigurationError) as captured:
        build_whole_output_detector(resources, corpus)
    _assert_content_free_error(captured.value)
    assert fragment.value not in str(captured.value) + repr(captured.value)


def test_baseline_observes_violation_and_returns_complete_original_output() -> None:
    detector, _, bundle = _loaded()
    canary = _first_canary(bundle)
    raw = RAW_SENTINEL + " prefix " + canary.value + " suffix"

    result = detector.evaluate(raw, role=Role.GUEST, mode=DetectorMode.BASELINE)
    assert result.outcome is DetectorOutcome.ANSWERED
    assert result.reply == raw
    assert _detection(result, canary.canary_id).action is DetectionAction.OBSERVED


def test_guarded_violation_discards_raw_and_returns_only_resource_fixed_reply() -> None:
    detector, resources, bundle = _loaded()
    canary = _first_canary(bundle)
    raw = RAW_SENTINEL + " " + canary.value

    result = detector.evaluate(raw, role=Role.GUEST, mode=DetectorMode.GUARDED)
    rendered = repr(result) + result.model_dump_json() + repr(result.model_dump(mode="json"))
    assert result.outcome is DetectorOutcome.BLOCKED
    assert result.reply == resources.detector.value.guarded_fixed_reply  # type: ignore[union-attr]
    assert result.reply == FIXED_BLOCKED_REPLY
    assert RAW_SENTINEL not in rendered
    assert canary.value not in rendered
    assert _detection(result, canary.canary_id).action is DetectionAction.BLOCKED


def test_guarded_authorized_fragment_is_observed_and_does_not_block() -> None:
    detector, _, bundle = _loaded()
    fragment = _fragment_with_roles(bundle, (Role.SECURITY_REVIEWER,))
    raw = "synthetic prefix " + fragment.value + " synthetic suffix"

    result = detector.evaluate(
        raw,
        role=Role.SECURITY_REVIEWER,
        mode=DetectorMode.GUARDED,
    )
    evidence = _detection(result, fragment.fragment_id)
    assert result.outcome is DetectorOutcome.ANSWERED
    assert result.reply == raw
    assert evidence.violation is False
    assert evidence.action is DetectionAction.OBSERVED


def test_guarded_unauthorized_fragment_is_blocked_without_partial_return() -> None:
    detector, resources, bundle = _loaded()
    fragment = _fragment_with_roles(bundle, (Role.SECURITY_REVIEWER,))
    raw = RAW_SENTINEL + " " + fragment.value

    result = detector.evaluate(raw, role=Role.EMPLOYEE, mode=DetectorMode.GUARDED)
    evidence = _detection(result, fragment.fragment_id)
    assert result.outcome is DetectorOutcome.BLOCKED
    assert result.reply == resources.detector.value.guarded_fixed_reply  # type: ignore[union-attr]
    assert evidence.violation is True
    assert evidence.action is DetectionAction.BLOCKED
    assert RAW_SENTINEL not in result.model_dump_json()


def test_guarded_no_match_returns_complete_original_output() -> None:
    detector, _, _ = _loaded()
    raw = "A purely synthetic answer without fixture evidence."
    result = detector.evaluate(raw, role=Role.GUEST, mode=DetectorMode.GUARDED)
    assert result == DetectorResult(
        reply=raw,
        outcome=DetectorOutcome.ANSWERED,
        detections=(),
    )


@pytest.mark.parametrize("mode", [DetectorMode.BASELINE, DetectorMode.GUARDED])
def test_empty_output_is_valid_unmodified_and_has_no_detections(mode: DetectorMode) -> None:
    detector, _, _ = _loaded()
    result = detector.evaluate("", role=Role.GUEST, mode=mode)
    assert result.reply == ""
    assert result.outcome is DetectorOutcome.ANSWERED
    assert result.detections == ()


def test_full_output_boundary_is_at_least_adapter_max_and_never_truncates() -> None:
    detector, _, _ = _loaded()
    assert MAX_RAW_OUTPUT_BYTES == MAX_RESPONSE_BYTES
    raw = "x" * MAX_RAW_OUTPUT_BYTES
    result = detector.evaluate(raw, role=Role.GUEST, mode=DetectorMode.BASELINE)
    assert result.reply == raw


@pytest.mark.parametrize("raw", [None, b"bytes", [], 1, True, "\ud800"])
def test_invalid_output_type_or_encoding_uses_content_free_error(raw: Any) -> None:
    detector, _, _ = _loaded()
    with pytest.raises(DetectorInputError) as captured:
        detector.evaluate(raw, role=Role.GUEST, mode=DetectorMode.BASELINE)
    _assert_content_free_error(captured.value)


def test_over_limit_output_is_rejected_without_echo_or_partial_scan() -> None:
    detector, _, _ = _loaded()
    raw = RAW_SENTINEL + ("x" * MAX_RAW_OUTPUT_BYTES)
    with pytest.raises(DetectorInputError) as captured:
        detector.evaluate(raw, role=Role.GUEST, mode=DetectorMode.BASELINE)
    _assert_content_free_error(captured.value)


@pytest.mark.parametrize(
    ("role", "mode"),
    [
        ("guest", DetectorMode.BASELINE),
        (Role.GUEST, "baseline"),
        (None, DetectorMode.GUARDED),
    ],
)
def test_role_and_mode_must_be_closed_enums(role: Any, mode: Any) -> None:
    detector, _, _ = _loaded()
    with pytest.raises(DetectorInputError) as captured:
        detector.evaluate(RAW_SENTINEL, role=role, mode=mode)
    _assert_content_free_error(captured.value)


def test_detection_evidence_direct_construction_enforces_canary_and_block_rules() -> None:
    for detection_type in (
        DetectionType.DOCUMENT_CANARY,
        DetectionType.SYSTEM_CANARY,
    ):
        with pytest.raises(ValidationError) as captured:
            DetectionEvidence(
                type=detection_type,
                evidence_id=RAW_SENTINEL,
                violation=False,
                action=DetectionAction.OBSERVED,
            )
        _assert_content_free_error(captured.value)

    with pytest.raises(ValidationError) as captured:
        DetectionEvidence(
            type=DetectionType.UNAUTHORIZED_PROTECTED_FRAGMENT,
            evidence_id=RAW_SENTINEL,
            violation=False,
            action=DetectionAction.BLOCKED,
        )
    _assert_content_free_error(captured.value)


def test_evidence_and_result_are_closed_frozen_sorted_and_minimized() -> None:
    evidence = DetectionEvidence(
        type=DetectionType.DOCUMENT_CANARY,
        evidence_id="opaque-id",
        violation=True,
        action=DetectionAction.OBSERVED,
    )
    assert set(evidence.model_dump(mode="json")) == {
        "type",
        "evidence_id",
        "violation",
        "action",
    }
    with pytest.raises(ValidationError):
        DetectionEvidence.model_validate({**evidence.model_dump(), "raw": RAW_SENTINEL})
    with pytest.raises(ValidationError):
        evidence.evidence_id = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        DetectorResult(
            reply="answer",
            outcome=DetectorOutcome.ANSWERED,
            detections=(evidence, evidence),
        )


def test_direct_detector_construction_and_mutation_cannot_bypass_factory() -> None:
    with pytest.raises(DetectorConfigurationError) as captured:
        WholeOutputDetector((), RAW_SENTINEL)
    _assert_content_free_error(captured.value)

    detector, _, _ = _loaded()
    with pytest.raises(AttributeError, match="immutable"):
        detector._fixed_reply = RAW_SENTINEL  # type: ignore[attr-defined]


def test_factory_configuration_error_does_not_echo_marker_or_evidence() -> None:
    _, resources, bundle = _loaded()
    documents = list(bundle.corpus.documents)
    first = documents[0].canaries[0]
    duplicate = documents[1].canaries[0].model_copy(
        update={"canary_id": first.canary_id, "value": RAW_SENTINEL}
    )
    documents[1] = documents[1].model_copy(update={"canaries": (duplicate,)})
    corpus: Corpus = bundle.corpus.model_copy(update={"documents": tuple(documents)})

    with pytest.raises(DetectorConfigurationError) as captured:
        build_whole_output_detector(resources, corpus)
    rendered = str(captured.value) + repr(captured.value)
    assert RAW_SENTINEL not in rendered
    assert first.canary_id not in rendered
    assert _system_marker(resources) not in rendered


def test_detector_package_import_performs_no_resource_file_network_or_db_io() -> None:
    script = """
import importlib.resources
import pathlib
import socket
import dataguard.config
import dataguard.domain
import dataguard.resources

def forbidden(*args, **kwargs):
    raise RuntimeError("I/O attempted")

importlib.resources.files = forbidden
pathlib.Path.read_bytes = forbidden
pathlib.Path.read_text = forbidden
socket.socket = forbidden
import dataguard.detector
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
