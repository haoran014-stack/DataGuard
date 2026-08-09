"""Unit tests for the framework-independent synthetic-v1 domain layer."""

from __future__ import annotations

from collections.abc import Iterable

import pytest
from pydantic import ValidationError

from dataguard.domain import (
    AttackFamily,
    Canary,
    Classification,
    Corpus,
    Document,
    ExpectedAssertions,
    Identity,
    IdentityTable,
    Language,
    ProtectedFragment,
    Role,
    Scenario,
    ScenarioFamily,
    ScenarioSet,
)


ROLE_MATRIX = {
    Classification.PUBLIC: (Role.GUEST, Role.EMPLOYEE, Role.SECURITY_REVIEWER),
    Classification.INTERNAL: (Role.EMPLOYEE, Role.SECURITY_REVIEWER),
    Classification.CONFIDENTIAL: (Role.SECURITY_REVIEWER,),
}


def make_identity_table() -> IdentityTable:
    return IdentityTable(
        version="synthetic-v1",
        synthetic=True,
        identities=[
            Identity(subject_id=f"{role.value}-{index}", role=role)
            for role in Role
            for index in range(1, 3)
        ],
    )


def make_document(
    classification: Classification,
    language: Language,
    index: int,
) -> Document:
    suffix = f"{classification.value}-{language.value}-{index:02d}"
    roles = ROLE_MATRIX[classification]
    return Document(
        doc_id=f"doc-{suffix}",
        title=f"Synthetic {suffix}",
        classification=classification,
        allowed_roles=roles,
        language=language,
        content=f"Synthetic fact anchor {suffix}.",
        canaries=[Canary(canary_id=f"canary-{suffix}", value=f"CANARY-{suffix}")],
        protected_fragments=[
            ProtectedFragment(
                fragment_id=f"fragment-{suffix}",
                value=f"FRAGMENT-{suffix}",
                allowed_roles=roles,
            )
        ],
        source_kind="synthetic",
        license="MIT",
        content_warning="Synthetic security-test content; no real personal data.",
        adversarial_fixture=False,
    )


def make_documents() -> list[Document]:
    return [
        make_document(classification, language, index)
        for classification in Classification
        for language in Language
        for index in range(1, 6)
    ]


def make_corpus(documents: Iterable[Document] | None = None) -> Corpus:
    return Corpus(
        corpus_version="synthetic-v1",
        identity_table_version="synthetic-v1",
        synthetic=True,
        documents=list(documents if documents is not None else make_documents()),
    )


def make_scenario(
    scenario_id: str,
    family: ScenarioFamily,
    language: Language,
    target: Document,
) -> Scenario:
    is_qa = family is ScenarioFamily.AUTHORIZED_QA
    return Scenario(
        scenario_id=scenario_id,
        family=family,
        language=language,
        subject_id="security_reviewer-1",
        question="What is the synthetic fact?",
        corpus_version="synthetic-v1",
        expected=ExpectedAssertions(
            must_include=("Synthetic fact anchor",) if is_qa else (),
            any_of=(),
            must_not_include=(),
        ),
        attack_target_ids=(target.doc_id,),
        forbidden_evidence_ids=() if is_qa else (target.canaries[0].canary_id,),
    )


def make_scenarios() -> list[Scenario]:
    documents = make_documents()
    scenarios = [
        make_scenario(
            scenario_id=f"qa-{index:02d}",
            family=ScenarioFamily.AUTHORIZED_QA,
            language=document.language,
            target=document,
        )
        for index, document in enumerate(documents, start=1)
    ]
    attack_families = (
        ScenarioFamily.DIRECT_PROMPT_INJECTION,
        ScenarioFamily.INDIRECT_DOCUMENT_INJECTION,
        ScenarioFamily.CROSS_ROLE_RETRIEVAL,
        ScenarioFamily.SYSTEM_PROMPT_INDUCEMENT,
    )
    for family_index, family in enumerate(attack_families):
        for language_index, language in enumerate(Language):
            for index in range(1, 5):
                target = documents[(family_index * 8 + language_index * 4 + index - 1) % 30]
                scenarios.append(
                    make_scenario(
                        scenario_id=f"{family.value}-{language.value}-{index:02d}",
                        family=family,
                        language=language,
                        target=target,
                    )
                )
    return scenarios


def make_scenario_set(scenarios: Iterable[Scenario] | None = None) -> ScenarioSet:
    return ScenarioSet(
        scenario_set_version="synthetic-v1",
        corpus_version="synthetic-v1",
        synthetic=True,
        scenarios=list(scenarios if scenarios is not None else make_scenarios()),
    )


def test_valid_aggregate_models_and_role_resolution() -> None:
    identities = make_identity_table()
    corpus = make_corpus()
    scenario_set = make_scenario_set()

    assert identities.role_for("guest-1") is Role.GUEST
    assert identities.role_for("missing-subject") is None
    assert len(corpus.documents) == 30
    assert len(scenario_set.scenarios) == 62
    assert set(AttackFamily) == {
        AttackFamily.DIRECT_PROMPT_INJECTION,
        AttackFamily.INDIRECT_DOCUMENT_INJECTION,
        AttackFamily.CROSS_ROLE_RETRIEVAL,
        AttackFamily.SYSTEM_PROMPT_INDUCEMENT,
    }


def test_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Identity.model_validate(
            {"subject_id": "guest-1", "role": "guest", "caller_role": "employee"}
        )


@pytest.mark.parametrize("bad_role", ["administrator", "reviewer", "Guest"])
def test_models_reject_invalid_enum_values(bad_role: str) -> None:
    with pytest.raises(ValidationError):
        Identity.model_validate({"subject_id": "guest-1", "role": bad_role})


def test_models_reject_unknown_versions() -> None:
    payload = make_identity_table().model_dump(mode="json")
    payload["version"] = "synthetic-v2"

    with pytest.raises(ValidationError, match="literal_error"):
        IdentityTable.model_validate(payload)


def test_subject_id_accepts_contract_boundaries_and_character_set() -> None:
    boundary = "A" + ("b" * 125) + ":Z"
    identity = Identity(subject_id=boundary, role=Role.GUEST)

    assert len(identity.subject_id) == 128
    assert identity.subject_id.endswith(":Z")


def test_subject_id_rejects_more_than_128_characters() -> None:
    with pytest.raises(ValidationError, match="string_too_long"):
        Identity(subject_id="A" * 129, role=Role.GUEST)


def test_plain_contract_ids_accept_128_characters_without_subject_pattern() -> None:
    plain_id = "!" * 128
    canary = Canary(canary_id=plain_id, value="synthetic marker")

    assert canary.canary_id == plain_id


def test_plain_contract_ids_reject_more_than_128_characters() -> None:
    with pytest.raises(ValidationError, match="string_too_long"):
        Canary(canary_id="!" * 129, value="synthetic marker")


def test_assertions_reject_more_than_500_characters() -> None:
    with pytest.raises(ValidationError, match="string_too_long"):
        ExpectedAssertions(
            must_include=("x" * 501,),
            any_of=(),
            must_not_include=(),
        )


def test_document_rejects_schema_invalid_role_order() -> None:
    document = make_document(Classification.PUBLIC, Language.EN, 1)
    payload = document.model_dump(mode="json")
    payload["allowed_roles"] = ["employee", "guest", "security_reviewer"]

    with pytest.raises(ValidationError, match="cumulative classification matrix"):
        Document.model_validate(payload)


def test_identity_table_rejects_wrong_fixed_distribution() -> None:
    with pytest.raises(ValidationError, match="exactly two identities per role"):
        IdentityTable(
            version="synthetic-v1",
            synthetic=True,
            identities=[
                Identity(subject_id=f"guest-{index}", role=Role.GUEST)
                for index in range(1, 7)
            ],
        )


def test_corpus_rejects_wrong_fixed_distribution() -> None:
    documents = make_documents()
    documents[-1] = make_document(Classification.PUBLIC, Language.EN, 99)

    with pytest.raises(ValidationError, match="exactly ten documents"):
        make_corpus(documents)


def test_scenario_set_rejects_wrong_fixed_distribution() -> None:
    scenarios = make_scenarios()
    target = make_documents()[0]
    scenarios[-1] = make_scenario(
        "replacement-direct-en-99",
        ScenarioFamily.DIRECT_PROMPT_INJECTION,
        Language.EN,
        target,
    )

    with pytest.raises(ValidationError, match="locked family distribution"):
        make_scenario_set(scenarios)


@pytest.mark.parametrize(
    "factory",
    [make_identity_table, make_corpus, make_scenario_set],
)
def test_models_round_trip_through_canonical_json(factory: object) -> None:
    model = factory()  # type: ignore[operator]
    restored = type(model).model_validate_json(model.model_dump_json())

    assert restored == model
    assert restored.model_dump(mode="json") == model.model_dump(mode="json")
