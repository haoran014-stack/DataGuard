"""Byte, YAML, JSON Schema, and typed-model loading for synthetic-v1."""

from __future__ import annotations

import codecs
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ValidationError
from yaml.nodes import MappingNode

from dataguard.domain import Corpus, IdentityTable, ScenarioSet
from dataguard.validation.issues import ValidationIssue, stable_issue_order


ModelT = TypeVar("ModelT", bound=BaseModel)


class _DuplicateKeyError(yaml.YAMLError):
    def __init__(self, line: int, column: int) -> None:
        super().__init__("duplicate mapping key")
        self.line = line
        self.column = column


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """SafeLoader variant that rejects explicit and merged duplicate keys."""

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Any, Any]:
        if not isinstance(node, MappingNode):
            return super().construct_mapping(node, deep=deep)

        self.flatten_mapping(node)
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=False)
            try:
                duplicate = key in seen
                seen.add(key)
            except TypeError as error:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable key",
                    key_node.start_mark,
                ) from error
            if duplicate:
                raise _DuplicateKeyError(
                    line=key_node.start_mark.line + 1,
                    column=key_node.start_mark.column + 1,
                )
        return super().construct_mapping(node, deep=deep)


@dataclass(frozen=True, slots=True)
class FixtureLoadResult(Generic[ModelT]):
    fixture: ModelT | None
    sha256: str
    issues: tuple[ValidationIssue, ...]

    @property
    def ok(self) -> bool:
        return self.fixture is not None and not self.issues


@dataclass(frozen=True, slots=True)
class FixtureBundle:
    identities: IdentityTable
    corpus: Corpus
    scenarios: ScenarioSet
    identity_sha256: str
    corpus_sha256: str
    scenario_sha256: str


@dataclass(frozen=True, slots=True)
class FixtureBundleResult:
    bundle: FixtureBundle | None
    issues: tuple[ValidationIssue, ...]

    @property
    def ok(self) -> bool:
        return self.bundle is not None and not self.issues


def sha256_bytes(raw: bytes) -> str:
    """Hash the exact committed bytes without newline or Unicode normalization."""

    return hashlib.sha256(raw).hexdigest()


def _read_utf8_lf(path: Path, label: str) -> tuple[bytes, str | None, tuple[ValidationIssue, ...]]:
    try:
        raw = path.read_bytes()
    except OSError:
        return b"", None, (ValidationIssue.create("fixture_read_error", (label,)),)

    issues: list[ValidationIssue] = []
    if raw.startswith(codecs.BOM_UTF8):
        issues.append(ValidationIssue.create("fixture_utf8_bom", (label, "$bytes")))
    if b"\r" in raw:
        issues.append(ValidationIssue.create("fixture_non_lf_newline", (label, "$bytes")))

    text: str | None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = None
        issues.append(ValidationIssue.create("fixture_invalid_utf8", (label, "$bytes")))

    return raw, text, tuple(sorted(issues, key=stable_issue_order))


def _safe_yaml_mapping(text: str, label: str) -> tuple[dict[str, Any] | None, tuple[ValidationIssue, ...]]:
    try:
        loaded = yaml.load(text, Loader=_UniqueKeySafeLoader)
    except _DuplicateKeyError as error:
        return None, (
            ValidationIssue.create(
                "yaml_duplicate_key",
                (label, "$yaml", error.line, error.column),
            ),
        )
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        path: tuple[str | int, ...] = (label, "$yaml")
        if mark is not None:
            path += (mark.line + 1, mark.column + 1)
        return None, (ValidationIssue.create("yaml_parse_error", path),)

    if not isinstance(loaded, dict):
        return None, (ValidationIssue.create("yaml_root_type", (label,)),)
    return loaded, ()


def _load_schema(path: Path, label: str) -> tuple[dict[str, Any] | None, tuple[ValidationIssue, ...]]:
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None, (ValidationIssue.create("schema_read_error", (label, "$schema")),)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError:
        return None, (ValidationIssue.create("schema_definition_error", (label, "$schema")),)
    return schema, ()


def _schema_issues(
    payload: dict[str, Any],
    schema: dict[str, Any],
    label: str,
) -> tuple[ValidationIssue, ...]:
    validator = Draft202012Validator(schema)
    errors = sorted(
        validator.iter_errors(payload),
        key=lambda error: (
            tuple(f"{type(part).__name__}:{part}" for part in error.absolute_path),
            str(error.validator),
        ),
    )
    issues = {
        ValidationIssue.create(
            "schema_validation_error",
            (label, *(part for part in error.absolute_path if isinstance(part, (str, int)))),
        )
        for error in errors
    }
    return tuple(sorted(issues, key=stable_issue_order))


def _model_issues(error: ValidationError, label: str) -> tuple[ValidationIssue, ...]:
    issues = {
        ValidationIssue.create(
            "model_validation_error",
            (label, *(part for part in item["loc"] if isinstance(part, (str, int)))),
        )
        for item in error.errors(include_url=False, include_context=False, include_input=False)
    }
    return tuple(sorted(issues, key=stable_issue_order))


def load_typed_yaml_fixture(
    fixture_path: Path,
    schema_path: Path,
    model_type: type[ModelT],
    *,
    label: str,
) -> FixtureLoadResult[ModelT]:
    """Load bytes, reject unsafe YAML, validate schema, then build a typed model."""

    raw, text, byte_issues = _read_utf8_lf(fixture_path, label)
    digest = sha256_bytes(raw)
    if byte_issues or text is None:
        return FixtureLoadResult(fixture=None, sha256=digest, issues=byte_issues)

    payload, yaml_issues = _safe_yaml_mapping(text, label)
    if yaml_issues or payload is None:
        return FixtureLoadResult(fixture=None, sha256=digest, issues=yaml_issues)

    schema, schema_load_issues = _load_schema(schema_path, label)
    if schema_load_issues or schema is None:
        return FixtureLoadResult(fixture=None, sha256=digest, issues=schema_load_issues)

    validation_issues = _schema_issues(payload, schema, label)
    if validation_issues:
        return FixtureLoadResult(fixture=None, sha256=digest, issues=validation_issues)

    try:
        fixture = model_type.model_validate(payload)
    except ValidationError as error:
        return FixtureLoadResult(
            fixture=None,
            sha256=digest,
            issues=_model_issues(error, label),
        )
    return FixtureLoadResult(fixture=fixture, sha256=digest, issues=())


def load_fixture_bundle(project_root: Path) -> FixtureBundleResult:
    """Load all three committed-intent fixtures without cross-record semantics."""

    data_dir = project_root / "data" / "synthetic-v1"
    contract_dir = project_root / "docs" / "contracts"
    identities = load_typed_yaml_fixture(
        data_dir / "identities.yaml",
        contract_dir / "identity-table.schema.json",
        IdentityTable,
        label="identities",
    )
    corpus = load_typed_yaml_fixture(
        data_dir / "corpus.yaml",
        contract_dir / "corpus.schema.json",
        Corpus,
        label="corpus",
    )
    scenarios = load_typed_yaml_fixture(
        data_dir / "scenarios.yaml",
        contract_dir / "scenario-set.schema.json",
        ScenarioSet,
        label="scenarios",
    )

    issues = tuple(
        sorted((*identities.issues, *corpus.issues, *scenarios.issues), key=stable_issue_order)
    )
    if issues or identities.fixture is None or corpus.fixture is None or scenarios.fixture is None:
        return FixtureBundleResult(bundle=None, issues=issues)
    return FixtureBundleResult(
        bundle=FixtureBundle(
            identities=identities.fixture,
            corpus=corpus.fixture,
            scenarios=scenarios.fixture,
            identity_sha256=identities.sha256,
            corpus_sha256=corpus.sha256,
            scenario_sha256=scenarios.sha256,
        ),
        issues=(),
    )

