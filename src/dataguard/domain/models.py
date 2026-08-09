"""Framework-independent Pydantic models for committed synthetic data.

These types intentionally have no dependency on FastAPI, SQLAlchemy, Ollama,
vector stores, HTTP transports, or persistence concerns.  JSON Schema and
cross-record semantic validation are separate validation layers.
"""

from __future__ import annotations

from collections import Counter
from enum import Enum
from typing import Annotated, ClassVar, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StringConstraints,
    model_validator,
)


SYNTHETIC_VERSION = "synthetic-v1"

SubjectId = Annotated[
    str,
    StringConstraints(
        strict=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
    ),
]
ContractId = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=128)]
ShortText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=120)]
ContentText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=1200)]
QuestionText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=2000)]
EvidenceValue = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=512)]
WarningText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=500)]
AssertionText = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=500)]


class Role(str, Enum):
    """Cumulative synthetic roles, from least to most privileged."""

    GUEST = "guest"
    EMPLOYEE = "employee"
    SECURITY_REVIEWER = "security_reviewer"


class Classification(str, Enum):
    """Synthetic document classifications."""

    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"


class Language(str, Enum):
    """Languages present in synthetic-v1."""

    EN = "en"
    ZH = "zh"


class AttackFamily(str, Enum):
    """The four locked attack families; authorized QA is not an attack."""

    DIRECT_PROMPT_INJECTION = "direct_prompt_injection"
    INDIRECT_DOCUMENT_INJECTION = "indirect_document_injection"
    CROSS_ROLE_RETRIEVAL = "cross_role_retrieval"
    SYSTEM_PROMPT_INDUCEMENT = "system_prompt_inducement"


class ScenarioFamily(str, Enum):
    """All scenario families, including the authorized QA control family."""

    AUTHORIZED_QA = "authorized_qa"
    DIRECT_PROMPT_INJECTION = AttackFamily.DIRECT_PROMPT_INJECTION.value
    INDIRECT_DOCUMENT_INJECTION = AttackFamily.INDIRECT_DOCUMENT_INJECTION.value
    CROSS_ROLE_RETRIEVAL = AttackFamily.CROSS_ROLE_RETRIEVAL.value
    SYSTEM_PROMPT_INDUCEMENT = AttackFamily.SYSTEM_PROMPT_INDUCEMENT.value


ROLE_MATRIX: dict[Classification, tuple[Role, ...]] = {
    Classification.PUBLIC: (Role.GUEST, Role.EMPLOYEE, Role.SECURITY_REVIEWER),
    Classification.INTERNAL: (Role.EMPLOYEE, Role.SECURITY_REVIEWER),
    Classification.CONFIDENTIAL: (Role.SECURITY_REVIEWER,),
}


class ClosedModel(BaseModel):
    """Base type that rejects forward-incompatible or misspelled fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


class Identity(ClosedModel):
    subject_id: SubjectId
    role: Role


class IdentityTable(ClosedModel):
    version: Literal["synthetic-v1"]
    synthetic: Literal[True]
    identities: tuple[Identity, ...] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def require_locked_role_distribution(self) -> Self:
        counts = Counter(identity.role for identity in self.identities)
        if counts != Counter({role: 2 for role in Role}):
            raise ValueError("identity table must contain exactly two identities per role")
        return self

    def role_for(self, subject_id: str) -> Role | None:
        """Resolve a synthetic role without accepting caller-supplied roles."""

        return next(
            (identity.role for identity in self.identities if identity.subject_id == subject_id),
            None,
        )


class Canary(ClosedModel):
    canary_id: ContractId
    value: EvidenceValue


class ProtectedFragment(ClosedModel):
    fragment_id: ContractId
    value: EvidenceValue
    allowed_roles: tuple[Role, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def require_unique_roles(self) -> Self:
        if len(set(self.allowed_roles)) != len(self.allowed_roles):
            raise ValueError("protected fragment roles must be unique")
        return self


class Document(ClosedModel):
    doc_id: ContractId
    title: ShortText
    classification: Classification
    allowed_roles: tuple[Role, ...] = Field(min_length=1, max_length=3)
    language: Language
    content: ContentText
    canaries: tuple[Canary, ...] = Field(min_length=1, max_length=1)
    protected_fragments: tuple[ProtectedFragment, ...]
    source_kind: Literal["synthetic"]
    license: Literal["MIT"]
    content_warning: WarningText
    adversarial_fixture: StrictBool

    _role_matrix: ClassVar[dict[Classification, tuple[Role, ...]]] = ROLE_MATRIX

    @model_validator(mode="after")
    def require_cumulative_document_roles(self) -> Self:
        expected = self._role_matrix[self.classification]
        if self.allowed_roles != expected:
            raise ValueError("document roles must match its cumulative classification matrix")
        return self


class Corpus(ClosedModel):
    corpus_version: Literal["synthetic-v1"]
    identity_table_version: Literal["synthetic-v1"]
    synthetic: Literal[True]
    documents: tuple[Document, ...] = Field(min_length=30, max_length=30)

    @model_validator(mode="after")
    def require_locked_document_distribution(self) -> Self:
        classifications = Counter(document.classification for document in self.documents)
        if classifications != Counter({classification: 10 for classification in Classification}):
            raise ValueError("corpus must contain exactly ten documents per classification")

        class_languages = Counter(
            (document.classification, document.language) for document in self.documents
        )
        expected = Counter(
            {
                (classification, language): 5
                for classification in Classification
                for language in Language
            }
        )
        if class_languages != expected:
            raise ValueError("each classification must contain five documents per language")
        return self


class ExpectedAssertions(ClosedModel):
    must_include: tuple[AssertionText, ...]
    any_of: tuple[AssertionText, ...]
    must_not_include: tuple[AssertionText, ...]

    @model_validator(mode="after")
    def require_unique_assertions(self) -> Self:
        for values in (self.must_include, self.any_of, self.must_not_include):
            if len(values) != len(set(values)):
                raise ValueError("expected assertion lists must not contain duplicates")
        return self


class Scenario(ClosedModel):
    scenario_id: ContractId
    family: ScenarioFamily
    language: Language
    subject_id: SubjectId
    question: QuestionText
    corpus_version: Literal["synthetic-v1"]
    expected: ExpectedAssertions
    attack_target_ids: tuple[ContractId, ...]
    forbidden_evidence_ids: tuple[ContractId, ...]

    @model_validator(mode="after")
    def require_family_shape(self) -> Self:
        if len(self.attack_target_ids) != len(set(self.attack_target_ids)):
            raise ValueError("scenario target document identifiers must be unique")
        if len(self.forbidden_evidence_ids) != len(set(self.forbidden_evidence_ids)):
            raise ValueError("scenario forbidden evidence identifiers must be unique")

        if self.family is ScenarioFamily.AUTHORIZED_QA:
            if len(self.attack_target_ids) != 1:
                raise ValueError("authorized QA must target exactly one document")
            if not self.expected.must_include and not self.expected.any_of:
                raise ValueError("authorized QA requires at least one positive fact assertion")
        else:
            if not self.attack_target_ids:
                raise ValueError("attack scenarios require at least one target document")
            if not self.forbidden_evidence_ids:
                raise ValueError("attack scenarios require at least one forbidden evidence identifier")
        return self


class ScenarioSet(ClosedModel):
    scenario_set_version: Literal["synthetic-v1"]
    corpus_version: Literal["synthetic-v1"]
    synthetic: Literal[True]
    scenarios: tuple[Scenario, ...] = Field(min_length=62, max_length=62)

    @model_validator(mode="after")
    def require_locked_scenario_distribution(self) -> Self:
        family_counts = Counter(scenario.family for scenario in self.scenarios)
        expected_families = Counter(
            {
                ScenarioFamily.AUTHORIZED_QA: 30,
                ScenarioFamily.DIRECT_PROMPT_INJECTION: 8,
                ScenarioFamily.INDIRECT_DOCUMENT_INJECTION: 8,
                ScenarioFamily.CROSS_ROLE_RETRIEVAL: 8,
                ScenarioFamily.SYSTEM_PROMPT_INDUCEMENT: 8,
            }
        )
        if family_counts != expected_families:
            raise ValueError("scenario set must contain the locked family distribution")

        attack_languages = Counter(
            (scenario.family, scenario.language)
            for scenario in self.scenarios
            if scenario.family is not ScenarioFamily.AUTHORIZED_QA
        )
        expected_languages = Counter(
            {
                (family, language): 4
                for family in ScenarioFamily
                if family is not ScenarioFamily.AUTHORIZED_QA
                for language in Language
            }
        )
        if attack_languages != expected_languages:
            raise ValueError("each attack family must contain four scenarios per language")
        return self
