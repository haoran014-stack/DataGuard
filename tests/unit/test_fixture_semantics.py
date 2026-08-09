"""Negative and positive tests for cross-record synthetic fixture semantics."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from dataguard.domain import ExpectedAssertions, Role
from dataguard.validation import (
    FixtureBundle,
    load_fixture_bundle,
    validate_fixture_semantics,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def valid_bundle() -> FixtureBundle:
    result = load_fixture_bundle(PROJECT_ROOT)
    assert result.bundle is not None, [issue.as_dict() for issue in result.issues]
    return result.bundle


def replace_identity(bundle: FixtureBundle, index: int, **updates: object) -> FixtureBundle:
    identities = list(bundle.identities.identities)
    identities[index] = identities[index].model_copy(update=updates)
    return replace(
        bundle,
        identities=bundle.identities.model_copy(update={"identities": tuple(identities)}),
    )


def replace_document(bundle: FixtureBundle, index: int, document: object) -> FixtureBundle:
    documents = list(bundle.corpus.documents)
    documents[index] = document  # type: ignore[assignment]
    return replace(
        bundle,
        corpus=bundle.corpus.model_copy(update={"documents": tuple(documents)}),
    )


def replace_scenario(bundle: FixtureBundle, index: int, **updates: object) -> FixtureBundle:
    scenarios = list(bundle.scenarios.scenarios)
    scenarios[index] = scenarios[index].model_copy(update=updates)
    return replace(
        bundle,
        scenarios=bundle.scenarios.model_copy(update={"scenarios": tuple(scenarios)}),
    )


def issue_codes(bundle: FixtureBundle) -> list[str]:
    return [issue.code for issue in validate_fixture_semantics(bundle)]


def test_committed_fixture_bundle_has_no_semantic_issues() -> None:
    assert validate_fixture_semantics(valid_bundle()) == ()


@pytest.mark.parametrize(
    ("duplicate_kind", "expected_code"),
    [
        ("subject", "semantic_duplicate_subject_id"),
        ("document", "semantic_duplicate_document_id"),
        ("scenario", "semantic_duplicate_scenario_id"),
        ("canary", "semantic_duplicate_canary_id"),
        ("fragment", "semantic_duplicate_fragment_id"),
    ],
)
def test_duplicate_identifiers_are_reported(
    duplicate_kind: str,
    expected_code: str,
) -> None:
    bundle = valid_bundle()
    if duplicate_kind == "subject":
        bundle = replace_identity(
            bundle,
            1,
            subject_id=bundle.identities.identities[0].subject_id,
        )
    elif duplicate_kind == "document":
        changed = bundle.corpus.documents[1].model_copy(
            update={"doc_id": bundle.corpus.documents[0].doc_id}
        )
        bundle = replace_document(bundle, 1, changed)
    elif duplicate_kind == "scenario":
        bundle = replace_scenario(
            bundle,
            1,
            scenario_id=bundle.scenarios.scenarios[0].scenario_id,
        )
    elif duplicate_kind == "canary":
        document = bundle.corpus.documents[1]
        changed_canary = document.canaries[0].model_copy(
            update={"canary_id": bundle.corpus.documents[0].canaries[0].canary_id}
        )
        bundle = replace_document(
            bundle,
            1,
            document.model_copy(update={"canaries": (changed_canary,)}),
        )
    else:
        document = bundle.corpus.documents[1]
        changed_fragment = document.protected_fragments[0].model_copy(
            update={
                "fragment_id": bundle.corpus.documents[0].protected_fragments[0].fragment_id
            }
        )
        bundle = replace_document(
            bundle,
            1,
            document.model_copy(update={"protected_fragments": (changed_fragment,)}),
        )

    assert expected_code in issue_codes(bundle)


def test_canary_and_fragment_identifiers_share_one_global_namespace() -> None:
    bundle = valid_bundle()
    document = bundle.corpus.documents[1]
    changed_fragment = document.protected_fragments[0].model_copy(
        update={"fragment_id": bundle.corpus.documents[0].canaries[0].canary_id}
    )
    bundle = replace_document(
        bundle,
        1,
        document.model_copy(update={"protected_fragments": (changed_fragment,)}),
    )

    codes = issue_codes(bundle)

    assert "semantic_evidence_id_reused" in codes
    assert "semantic_duplicate_fragment_id" not in codes


def test_fragment_roles_must_equal_source_document_roles() -> None:
    bundle = valid_bundle()
    document = bundle.corpus.documents[10]
    changed_fragment = document.protected_fragments[0].model_copy(
        update={"allowed_roles": (Role.GUEST,)}
    )
    bundle = replace_document(
        bundle,
        10,
        document.model_copy(update={"protected_fragments": (changed_fragment,)}),
    )

    assert "semantic_fragment_roles_mismatch" in issue_codes(bundle)


@pytest.mark.parametrize(
    ("reference_kind", "expected_code"),
    [
        ("subject", "semantic_unknown_scenario_subject"),
        ("target", "semantic_unknown_scenario_target"),
        ("evidence", "semantic_unknown_scenario_evidence"),
    ],
)
def test_unknown_scenario_references_are_reported(
    reference_kind: str,
    expected_code: str,
) -> None:
    bundle = valid_bundle()
    updates = {
        "subject": {"subject_id": "unknown-subject"},
        "target": {"attack_target_ids": ("unknown-document",)},
        "evidence": {"forbidden_evidence_ids": ("unknown-evidence",)},
    }[reference_kind]
    bundle = replace_scenario(bundle, 0, **updates)

    assert expected_code in issue_codes(bundle)


def test_authorized_qa_must_cover_every_document_exactly_once() -> None:
    bundle = valid_bundle()
    first = bundle.scenarios.scenarios[0]
    bundle = replace_scenario(
        bundle,
        1,
        attack_target_ids=first.attack_target_ids,
        forbidden_evidence_ids=first.forbidden_evidence_ids,
        expected=first.expected,
    )

    issues = validate_fixture_semantics(bundle)
    coverage = [issue for issue in issues if issue.code == "semantic_qa_document_coverage"]

    assert len(coverage) == 2
    assert {issue.path[2] for issue in coverage} == {0, 1}


def test_authorized_qa_subject_must_be_authorized_for_target() -> None:
    bundle = replace_scenario(valid_bundle(), 20, subject_id="guest-01")

    assert "semantic_qa_subject_unauthorized" in issue_codes(bundle)


@pytest.mark.parametrize(
    ("expected", "expected_code"),
    [
        (
            ExpectedAssertions(must_include=(), any_of=(), must_not_include=()),
            "semantic_qa_positive_assertion_required",
        ),
        (
            ExpectedAssertions(
                must_include=("The demo observatory opens at 09:00.", "not in target"),
                any_of=(),
                must_not_include=(),
            ),
            "semantic_qa_must_include_unanchored",
        ),
        (
            ExpectedAssertions(
                must_include=("The demo observatory opens at 09:00.",),
                any_of=("neither anchor one", "nor anchor two"),
                must_not_include=(),
            ),
            "semantic_qa_any_of_unanchored",
        ),
    ],
)
def test_authorized_qa_assertions_must_be_positively_anchored(
    expected: ExpectedAssertions,
    expected_code: str,
) -> None:
    bundle = replace_scenario(valid_bundle(), 0, expected=expected)

    assert expected_code in issue_codes(bundle)


def test_cross_role_scenario_requires_at_least_one_unauthorized_target() -> None:
    bundle = replace_scenario(valid_bundle(), 46, subject_id="security_reviewer-01")

    assert "semantic_cross_role_not_unauthorized" in issue_codes(bundle)


def test_forbidden_evidence_must_belong_to_a_declared_target() -> None:
    bundle = valid_bundle()
    unrelated = bundle.corpus.documents[1].canaries[0].canary_id
    bundle = replace_scenario(bundle, 30, forbidden_evidence_ids=(unrelated,))

    assert "semantic_evidence_target_mismatch" in issue_codes(bundle)


def test_validator_collects_all_independent_issues_without_short_circuiting() -> None:
    bundle = valid_bundle()
    bundle = replace_identity(
        bundle,
        1,
        subject_id=bundle.identities.identities[0].subject_id,
    )
    document = bundle.corpus.documents[10]
    changed_fragment = document.protected_fragments[0].model_copy(
        update={"allowed_roles": (Role.GUEST,)}
    )
    bundle = replace_document(
        bundle,
        10,
        document.model_copy(update={"protected_fragments": (changed_fragment,)}),
    )
    bundle = replace_scenario(
        bundle,
        0,
        subject_id="unknown-subject",
        attack_target_ids=("unknown-document",),
        forbidden_evidence_ids=("unknown-evidence",),
    )

    codes = set(issue_codes(bundle))

    assert {
        "semantic_duplicate_subject_id",
        "semantic_fragment_roles_mismatch",
        "semantic_unknown_scenario_subject",
        "semantic_unknown_scenario_target",
        "semantic_unknown_scenario_evidence",
    } <= codes


def test_issue_order_is_stable_and_issues_do_not_echo_identifiers_or_values() -> None:
    bundle = valid_bundle()
    raw_subject = "DO_NOT_ECHO_SUBJECT"
    raw_evidence = "DO_NOT_ECHO_EVIDENCE"
    bundle = replace_scenario(
        bundle,
        0,
        subject_id=raw_subject,
        forbidden_evidence_ids=(raw_evidence,),
    )

    first = validate_fixture_semantics(bundle)
    second = validate_fixture_semantics(bundle)
    rendered = repr([issue.as_dict() for issue in first])

    assert first == second
    assert raw_subject not in rendered
    assert raw_evidence not in rendered
    assert bundle.corpus.documents[0].doc_id not in rendered
    assert bundle.corpus.documents[0].canaries[0].value not in rendered
    assert all(
        all(not isinstance(part, str) or part in {
            "identities",
            "corpus",
            "documents",
            "scenarios",
            "subject_id",
            "doc_id",
            "scenario_id",
            "canaries",
            "canary_id",
            "protected_fragments",
            "fragment_id",
            "allowed_roles",
            "attack_target_ids",
            "forbidden_evidence_ids",
            "expected",
            "must_include",
            "any_of",
        }
        for part in issue.path)
        for issue in first
    )

