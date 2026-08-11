"""Closed delivery checks for the local HTTP demonstration client."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from dataguard.domain import Classification, Role, ScenarioFamily


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "dataguard_demo_client", ROOT / "scripts" / "demo_client.py"
)
assert SPEC is not None and SPEC.loader is not None
DEMO = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DEMO
SPEC.loader.exec_module(DEMO)


def test_fixed_demo_scenarios_exist_and_have_required_authorization_semantics() -> None:
    bundle, scenarios = DEMO.load_demo_scenarios(ROOT)
    identities = {
        identity.subject_id: identity.role for identity in bundle.identities.identities
    }
    documents = {document.doc_id: document for document in bundle.corpus.documents}

    cross_role = scenarios[DEMO.CROSS_ROLE_SCENARIO_ID]
    assert cross_role.family is ScenarioFamily.CROSS_ROLE_RETRIEVAL
    cross_role_subject = identities[cross_role.subject_id]
    assert any(
        cross_role_subject not in documents[target].allowed_roles
        for target in cross_role.attack_target_ids
    )

    indirect = scenarios[DEMO.INDIRECT_SCENARIO_ID]
    assert indirect.family is ScenarioFamily.INDIRECT_DOCUMENT_INJECTION
    assert any(documents[target].adversarial_fixture for target in indirect.attack_target_ids)

    canary = scenarios[DEMO.CANARY_BLOCK_SCENARIO_ID]
    assert canary.family in {
        ScenarioFamily.DIRECT_PROMPT_INJECTION,
        ScenarioFamily.SYSTEM_PROMPT_INDUCEMENT,
    }

    reviewer = scenarios[DEMO.REVIEWER_QA_SCENARIO_ID]
    assert reviewer.family is ScenarioFamily.AUTHORIZED_QA
    assert identities[reviewer.subject_id] is Role.SECURITY_REVIEWER
    assert all(
        documents[target].classification is Classification.CONFIDENTIAL
        and Role.SECURITY_REVIEWER in documents[target].allowed_roles
        for target in reviewer.attack_target_ids
    )


@pytest.mark.parametrize(
    "value",
    [
        "https://127.0.0.1:8000",
        "http://localhost:8000",
        "http://0.0.0.0:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:0",
        "http://127.0.0.1:65536",
        "http://user@127.0.0.1:8000",
        "http://127.0.0.1:8000/path",
        "http://127.0.0.1:8000?query=value",
        "http://127.0.0.1:8000/#fragment",
    ],
)
def test_api_base_uri_rejects_every_non_loopback_or_nonroot_shape(value: str) -> None:
    with pytest.raises(DEMO.DemoFailure, match="configuration is invalid"):
        DEMO.validated_api_base_uri(value)


def test_api_base_uri_accepts_only_explicit_loopback_port() -> None:
    assert DEMO.validated_api_base_uri("http://127.0.0.1:18000") == (
        "http://127.0.0.1:18000"
    )


def test_report_outputs_are_fixed_beneath_existing_artifacts(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    json_path, html_path = DEMO.report_output_paths(tmp_path)

    assert json_path == artifacts / "report.json"
    assert html_path == artifacts / "report.html"
    assert json_path.parent == artifacts
    assert html_path.parent == artifacts


def test_report_outputs_reject_missing_or_non_directory_artifacts(tmp_path: Path) -> None:
    with pytest.raises(DEMO.DemoFailure, match="report path is invalid"):
        DEMO.report_output_paths(tmp_path)

    (tmp_path / "artifacts").write_text("not-a-directory", encoding="utf-8")
    with pytest.raises(DEMO.DemoFailure, match="report path is invalid"):
        DEMO.report_output_paths(tmp_path)


def indirect_events(
    *,
    target_included: bool = True,
    authorized: bool = True,
    violation: bool | None = None,
    action: str = "blocked",
) -> tuple[dict[str, object], ...]:
    detections = [] if violation is None else [
        {"violation": violation, "action": action}
    ]
    return ({
        "retrieved_documents": [{
            "document_id": "target-doc" if target_included else "other-doc",
            "included_in_context": True,
            "authorized": authorized,
        }],
        "detections": detections,
    },)


def test_indirect_injection_accepts_blocked_with_violation_evidence() -> None:
    DEMO.validate_indirect_injection_evidence(
        DEMO.ChatFact(trace_id="00000000-0000-4000-8000-000000000001", outcome="blocked"),
        indirect_events(violation=True),
        ("target-doc",),
    )


def test_indirect_injection_accepts_answered_without_violation() -> None:
    DEMO.validate_indirect_injection_evidence(
        DEMO.ChatFact(trace_id="00000000-0000-4000-8000-000000000001", outcome="answered"),
        indirect_events(),
        ("target-doc",),
    )


@pytest.mark.parametrize(
    ("outcome", "events"),
    [
        ("answered", indirect_events(target_included=False)),
        ("answered", indirect_events(authorized=False)),
        ("answered", indirect_events(violation=True, action="observed")),
        ("blocked", indirect_events()),
    ],
)
def test_indirect_injection_rejects_incomplete_or_unsafe_evidence(
    outcome: str,
    events: tuple[dict[str, object], ...],
) -> None:
    with pytest.raises(DEMO.DemoFailure, match="indirect-injection evidence is invalid"):
        DEMO.validate_indirect_injection_evidence(
            DEMO.ChatFact(
                trace_id="00000000-0000-4000-8000-000000000001",
                outcome=outcome,
            ),
            events,
            ("target-doc",),
        )


def evidence_health() -> dict[str, object]:
    return {
        "status": "healthy",
        "evidence_readiness": True,
        "storage": {"status": "up", "backend": "postgresql"},
        "ollama": {"status": "up"},
    }


def test_health_accepts_only_complete_evidence_ready_dependencies() -> None:
    assert DEMO.health_is_evidence_ready(evidence_health()) is True


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        (None, "status", "degraded"),
        (None, "evidence_readiness", False),
        ("storage", "status", "down"),
        ("storage", "backend", "sqlite"),
        ("ollama", "status", "down"),
    ],
)
def test_health_rejects_every_non_evidence_ready_state(
    section: str | None, field: str, value: object
) -> None:
    health = evidence_health()
    if section is None:
        health[field] = value
    else:
        nested = health[section]
        assert isinstance(nested, dict)
        nested[field] = value
    assert DEMO.health_is_evidence_ready(health) is False


@pytest.mark.parametrize("detection_type", ["document_canary", "system_canary"])
def test_canary_block_accepts_only_canary_violation_types(detection_type: str) -> None:
    DEMO.validate_canary_block_evidence(
        DEMO.ChatFact(trace_id="00000000-0000-4000-8000-000000000001", outcome="blocked"),
        ({"detections": [{
            "type": detection_type,
            "violation": True,
            "action": "blocked",
        }]},),
    )


def test_canary_block_rejects_non_canary_violation_type() -> None:
    with pytest.raises(DEMO.DemoFailure, match="Canary evidence is invalid"):
        DEMO.validate_canary_block_evidence(
            DEMO.ChatFact(
                trace_id="00000000-0000-4000-8000-000000000001",
                outcome="blocked",
            ),
            ({"detections": [{
                "type": "unauthorized_protected_fragment",
                "violation": True,
                "action": "blocked",
            }]},),
        )


def reviewer_events(*, target_included: bool = True, authorized: bool = True):
    return ({"retrieved_documents": [{
        "document_id": "target-doc" if target_included else "other-doc",
        "included_in_context": True,
        "authorized": authorized,
    }]},)


def test_reviewer_qa_requires_authorized_target_in_context() -> None:
    DEMO.validate_reviewer_qa_evidence(
        DEMO.ChatFact(trace_id="00000000-0000-4000-8000-000000000001", outcome="answered"),
        reviewer_events(),
        ("target-doc",),
    )


@pytest.mark.parametrize(
    "events",
    [reviewer_events(target_included=False), reviewer_events(authorized=False)],
)
def test_reviewer_qa_rejects_missing_or_unauthorized_target(events) -> None:
    with pytest.raises(DEMO.DemoFailure, match="authorized-QA evidence is invalid"):
        DEMO.validate_reviewer_qa_evidence(
            DEMO.ChatFact(
                trace_id="00000000-0000-4000-8000-000000000001",
                outcome="answered",
            ),
            events,
            ("target-doc",),
        )
