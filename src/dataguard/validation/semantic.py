"""Deterministic cross-record semantics for a structurally valid fixture bundle."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable

from dataguard.domain import ScenarioFamily
from dataguard.validation.issues import ValidationIssue, stable_issue_order
from dataguard.validation.loading import FixtureBundle


def _duplicates(
    values: Iterable[tuple[str, tuple[str | int, ...]]],
    code: str,
) -> list[ValidationIssue]:
    """Report every occurrence after the first, without putting its ID in the issue."""

    seen: set[str] = set()
    issues: list[ValidationIssue] = []
    for value, path in values:
        if value in seen:
            issues.append(ValidationIssue.create(code, path))
        else:
            seen.add(value)
    return issues


def validate_fixture_semantics(bundle: FixtureBundle) -> tuple[ValidationIssue, ...]:
    """Return every independently decidable semantic issue in stable order.

    The bundle must already have passed byte, YAML, Draft 2020-12, and Pydantic
    validation. IDs and fixture values are used only as internal join keys; no
    issue message or path contains them.
    """

    issues: list[ValidationIssue] = []

    subject_occurrences: dict[str, list[tuple[int, object]]] = defaultdict(list)
    for identity_index, identity in enumerate(bundle.identities.identities):
        subject_occurrences[identity.subject_id].append((identity_index, identity))
    issues.extend(
        _duplicates(
            (
                (
                    identity.subject_id,
                    ("identities", "identities", identity_index, "subject_id"),
                )
                for identity_index, identity in enumerate(bundle.identities.identities)
            ),
            "semantic_duplicate_subject_id",
        )
    )

    document_occurrences: dict[str, list[tuple[int, object]]] = defaultdict(list)
    for document_index, document in enumerate(bundle.corpus.documents):
        document_occurrences[document.doc_id].append((document_index, document))
    issues.extend(
        _duplicates(
            (
                (
                    document.doc_id,
                    ("corpus", "documents", document_index, "doc_id"),
                )
                for document_index, document in enumerate(bundle.corpus.documents)
            ),
            "semantic_duplicate_document_id",
        )
    )

    scenario_occurrences: dict[str, list[int]] = defaultdict(list)
    for scenario_index, scenario in enumerate(bundle.scenarios.scenarios):
        scenario_occurrences[scenario.scenario_id].append(scenario_index)
    issues.extend(
        _duplicates(
            (
                (
                    scenario.scenario_id,
                    ("scenarios", "scenarios", scenario_index, "scenario_id"),
                )
                for scenario_index, scenario in enumerate(bundle.scenarios.scenarios)
            ),
            "semantic_duplicate_scenario_id",
        )
    )

    canary_values: list[tuple[str, tuple[str | int, ...]]] = []
    fragment_values: list[tuple[str, tuple[str | int, ...]]] = []
    evidence_occurrences: dict[
        str,
        list[tuple[int, tuple[str | int, ...]]],
    ] = defaultdict(list)
    for document_index, document in enumerate(bundle.corpus.documents):
        for canary_index, canary in enumerate(document.canaries):
            path = (
                "corpus",
                "documents",
                document_index,
                "canaries",
                canary_index,
                "canary_id",
            )
            canary_values.append((canary.canary_id, path))
            evidence_occurrences[canary.canary_id].append((document_index, path))
        for fragment_index, fragment in enumerate(document.protected_fragments):
            path = (
                "corpus",
                "documents",
                document_index,
                "protected_fragments",
                fragment_index,
                "fragment_id",
            )
            fragment_values.append((fragment.fragment_id, path))
            evidence_occurrences[fragment.fragment_id].append((document_index, path))
            if fragment.allowed_roles != document.allowed_roles:
                issues.append(
                    ValidationIssue.create(
                        "semantic_fragment_roles_mismatch",
                        (
                            "corpus",
                            "documents",
                            document_index,
                            "protected_fragments",
                            fragment_index,
                            "allowed_roles",
                        ),
                    )
                )

    issues.extend(_duplicates(canary_values, "semantic_duplicate_canary_id"))
    issues.extend(_duplicates(fragment_values, "semantic_duplicate_fragment_id"))
    issues.extend(
        _duplicates(
            (
                (evidence_id, path)
                for evidence_id, occurrences in evidence_occurrences.items()
                for _, path in occurrences
            ),
            "semantic_evidence_id_reused",
        )
    )

    qa_target_counts: Counter[str] = Counter()
    qa_coverage_decidable = all(
        len(occurrences) == 1 for occurrences in document_occurrences.values()
    )

    for scenario_index, scenario in enumerate(bundle.scenarios.scenarios):
        scenario_path = ("scenarios", "scenarios", scenario_index)
        subjects = subject_occurrences.get(scenario.subject_id, [])
        if not subjects:
            issues.append(
                ValidationIssue.create(
                    "semantic_unknown_scenario_subject",
                    (*scenario_path, "subject_id"),
                )
            )

        resolved_targets: list[object] = []
        targets_decidable = bool(scenario.attack_target_ids)
        for target_index, target_id in enumerate(scenario.attack_target_ids):
            target_occurrences = document_occurrences.get(target_id, [])
            if not target_occurrences:
                issues.append(
                    ValidationIssue.create(
                        "semantic_unknown_scenario_target",
                        (*scenario_path, "attack_target_ids", target_index),
                    )
                )
                targets_decidable = False
            elif len(target_occurrences) == 1:
                resolved_targets.append(target_occurrences[0][1])
            else:
                targets_decidable = False

        for evidence_index, evidence_id in enumerate(scenario.forbidden_evidence_ids):
            owners = evidence_occurrences.get(evidence_id, [])
            evidence_path = (*scenario_path, "forbidden_evidence_ids", evidence_index)
            if not owners:
                issues.append(
                    ValidationIssue.create("semantic_unknown_scenario_evidence", evidence_path)
                )
            elif len(owners) == 1:
                owner_document_index = owners[0][0]
                owner_document_id = bundle.corpus.documents[owner_document_index].doc_id
                if owner_document_id not in scenario.attack_target_ids:
                    issues.append(
                        ValidationIssue.create("semantic_evidence_target_mismatch", evidence_path)
                    )

        if scenario.family is ScenarioFamily.AUTHORIZED_QA:
            if len(scenario.attack_target_ids) == 1:
                target_occurrences = document_occurrences.get(scenario.attack_target_ids[0], [])
                if len(target_occurrences) == 1:
                    qa_target_counts[scenario.attack_target_ids[0]] += 1
                else:
                    qa_coverage_decidable = False
            else:
                qa_coverage_decidable = False

            if len(subjects) == 1 and targets_decidable and len(resolved_targets) == 1:
                subject = subjects[0][1]
                target = resolved_targets[0]
                if subject.role not in target.allowed_roles:
                    issues.append(
                        ValidationIssue.create(
                            "semantic_qa_subject_unauthorized",
                            (*scenario_path, "subject_id"),
                        )
                    )

            if targets_decidable and len(resolved_targets) == 1:
                content = resolved_targets[0].content
                positive_count = len(scenario.expected.must_include) + len(scenario.expected.any_of)
                if positive_count == 0:
                    issues.append(
                        ValidationIssue.create(
                            "semantic_qa_positive_assertion_required",
                            (*scenario_path, "expected"),
                        )
                    )
                for assertion_index, assertion in enumerate(scenario.expected.must_include):
                    if assertion not in content:
                        issues.append(
                            ValidationIssue.create(
                                "semantic_qa_must_include_unanchored",
                                (*scenario_path, "expected", "must_include", assertion_index),
                            )
                        )
                if scenario.expected.any_of and not any(
                    assertion in content for assertion in scenario.expected.any_of
                ):
                    issues.append(
                        ValidationIssue.create(
                            "semantic_qa_any_of_unanchored",
                            (*scenario_path, "expected", "any_of"),
                        )
                    )

        elif scenario.family is ScenarioFamily.CROSS_ROLE_RETRIEVAL:
            if len(subjects) == 1 and targets_decidable and resolved_targets:
                subject = subjects[0][1]
                if all(subject.role in target.allowed_roles for target in resolved_targets):
                    issues.append(
                        ValidationIssue.create(
                            "semantic_cross_role_not_unauthorized",
                            (*scenario_path, "attack_target_ids"),
                        )
                    )

    if qa_coverage_decidable:
        for document_index, document in enumerate(bundle.corpus.documents):
            if qa_target_counts[document.doc_id] != 1:
                issues.append(
                    ValidationIssue.create(
                        "semantic_qa_document_coverage",
                        ("corpus", "documents", document_index),
                    )
                )

    return tuple(sorted(set(issues), key=stable_issue_order))

