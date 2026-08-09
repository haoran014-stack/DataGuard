"""Explicit, duplicate-key-safe loader for Stage 2 package resources."""

from __future__ import annotations

import codecs
import hashlib
import re
import string
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, UUID4, ValidationError, model_validator
from yaml.nodes import MappingNode


FIXED_BLOCKED_REPLY = (
    "The response was blocked by DataGuard policy. / 响应已被 DataGuard 防护策略阻断。"
)
GENERATION_MODEL = "qwen2.5:3b-instruct"
EMBEDDING_MODEL = "qwen3-embedding:0.6b"
NORMALIZATION = ("NFKC", "casefold", "remove_zero_width", "normalize_whitespace")
ZERO_WIDTH_CODEPOINTS = ("U+200B", "U+200C", "U+200D", "U+2060", "U+FEFF")
DETECTION_TYPES = (
    "document_canary",
    "system_canary",
    "unauthorized_protected_fragment",
)
RESOURCE_NAMES = (
    "system-prompt.v1.yaml",
    "baseline-prompt.v1.yaml",
    "guarded-prompt.v1.yaml",
    "guard-policy.v1.yaml",
    "detector.v1.yaml",
)
_RESOURCE_PACKAGE = "dataguard.resources"
_SYSTEM_CANARY_PATTERN = re.compile(
    r"\bDG_SYNTHETIC_SYSTEM_CANARY_[A-Z0-9_]{8,128}\b"
)


class ResourceLoadError(Exception):
    """Fixed content-free resource failure safe for logging."""

    _MESSAGES = {
        "resource_unavailable": "A required DataGuard security resource is unavailable.",
        "resource_invalid": "A required DataGuard security resource is invalid.",
    }

    def __init__(self, code: Literal["resource_unavailable", "resource_invalid"]) -> None:
        self.code = code
        self.message = self._MESSAGES[code]
        super().__init__(self.message)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class _DuplicateKeyError(yaml.YAMLError):
    pass


class _UniqueKeySafeLoader(yaml.SafeLoader):
    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Any, Any]:
        if not isinstance(node, MappingNode):
            return super().construct_mapping(node, deep=deep)
        self.flatten_mapping(node)
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=False)
            try:
                if key in seen:
                    raise _DuplicateKeyError("duplicate mapping key")
                seen.add(key)
            except TypeError as error:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable key",
                    key_node.start_mark,
                ) from error
        return super().construct_mapping(node, deep=deep)


class _ClosedResource(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        hide_input_in_errors=True,
    )


def _template_fields(template: str) -> tuple[str, ...]:
    fields: list[str] = []
    try:
        for _, field_name, format_spec, conversion in string.Formatter().parse(template):
            if field_name is None:
                continue
            if format_spec or conversion or not field_name.isidentifier():
                raise ValueError
            fields.append(field_name)
    except ValueError:
        raise ValueError("prompt placeholder declaration is invalid") from None
    return tuple(fields)


class SystemPromptResource(_ClosedResource):
    version: Literal["1.0"]
    resource_type: Literal["system_prompt"]
    synthetic: Literal[True]
    system_canary_evidence_id: UUID4
    content: str = Field(min_length=1, max_length=4096)

    @model_validator(mode="after")
    def validate_system_canary(self) -> Self:
        if len(_SYSTEM_CANARY_PATTERN.findall(self.content)) != 1:
            raise ValueError("system Canary declaration is invalid")
        return self

    @property
    def system_canary_literal(self) -> str:
        """Return the reviewed marker only in runtime memory."""

        match = _SYSTEM_CANARY_PATTERN.search(self.content)
        if match is None:  # Model validation makes this unreachable.
            raise ResourceLoadError("resource_invalid")
        return match.group(0)


class BaselinePromptResource(_ClosedResource):
    version: Literal["1.0"]
    resource_type: Literal["prompt_template"]
    synthetic: Literal[True]
    mode: Literal["baseline"]
    isolation: Literal["weak_single_user_payload"]
    placeholders: tuple[str, ...]
    template: str = Field(min_length=1, max_length=8192)

    @model_validator(mode="after")
    def validate_placeholders(self) -> Self:
        expected = ("system_prompt", "documents_text", "question")
        if self.placeholders != expected or _template_fields(self.template) != expected:
            raise ValueError("baseline prompt declaration is invalid")
        return self


class GuardedMessageTemplate(_ClosedResource):
    slot: Literal["system", "documents", "query"]
    role: Literal["system", "user"]
    template: str = Field(min_length=1, max_length=8192)


class GuardedPromptResource(_ClosedResource):
    version: Literal["1.0"]
    resource_type: Literal["prompt_template"]
    synthetic: Literal[True]
    mode: Literal["guarded"]
    isolation: Literal["separate_system_document_query_messages"]
    placeholders: tuple[str, ...]
    messages: tuple[GuardedMessageTemplate, ...]

    @model_validator(mode="after")
    def validate_layout(self) -> Self:
        expected_placeholders = ("system_prompt", "documents_json", "question")
        expected_layout = (
            ("system", "system", ("system_prompt",)),
            ("documents", "user", ("documents_json",)),
            ("query", "user", ("question",)),
        )
        actual_layout = tuple(
            (message.slot, message.role, _template_fields(message.template))
            for message in self.messages
        )
        if self.placeholders != expected_placeholders or actual_layout != expected_layout:
            raise ValueError("guarded prompt declaration is invalid")
        return self


class LockedSettings(_ClosedResource):
    temperature: Literal[0]
    seed: Literal[42]
    generation_top_k: Literal[20]
    top_p: Literal[0.9]
    num_ctx: Literal[8192]
    num_predict: Literal[512]
    retrieval_top_k: Literal[4]
    stream: Literal[False]


class GuardPolicyResource(_ClosedResource):
    version: Literal["1.0"]
    resource_type: Literal["guard_policy"]
    synthetic: Literal[True]
    generation_model: Literal["qwen2.5:3b-instruct"]
    embedding_model: Literal["qwen3-embedding:0.6b"]
    guarded_fixed_reply: Literal[
        "The response was blocked by DataGuard policy. / 响应已被 DataGuard 防护策略阻断。"
    ]
    role_order: tuple[str, ...]
    classification_order: tuple[str, ...]
    guarded_steps: tuple[str, ...]
    settings: LockedSettings

    @model_validator(mode="after")
    def validate_sequences(self) -> Self:
        if self.role_order != ("guest", "employee", "security_reviewer"):
            raise ValueError("guard policy role order is invalid")
        if self.classification_order != ("public", "internal", "confidential"):
            raise ValueError("guard policy classification order is invalid")
        if self.guarded_steps != (
            "resolve_subject",
            "pre_retrieval_role_filter",
            "top4_vector_retrieval",
            "json_document_boundary",
            "message_isolation",
            "full_output_detection",
            "discard_and_fixed_block",
            "minimal_audit",
        ):
            raise ValueError("guard policy step order is invalid")
        return self


class DetectorResource(_ClosedResource):
    version: Literal["1.0"]
    resource_type: Literal["detector_definition"]
    synthetic: Literal[True]
    scan_scope: Literal["full_output_untruncated"]
    normalization: tuple[str, ...]
    zero_width_codepoints: tuple[str, ...]
    detection_types: tuple[str, ...]
    baseline_action: Literal["observed"]
    guarded_action: Literal["blocked"]
    raw_output_persistence: Literal["forbidden"]
    guarded_fixed_reply: Literal[
        "The response was blocked by DataGuard policy. / 响应已被 DataGuard 防护策略阻断。"
    ]

    @model_validator(mode="after")
    def validate_constants(self) -> Self:
        if (
            self.normalization != NORMALIZATION
            or self.zero_width_codepoints != ZERO_WIDTH_CODEPOINTS
            or self.detection_types != DETECTION_TYPES
        ):
            raise ValueError("detector definition constants are invalid")
        return self


ResourceModel = (
    SystemPromptResource
    | BaselinePromptResource
    | GuardedPromptResource
    | GuardPolicyResource
    | DetectorResource
)


@dataclass(frozen=True, slots=True)
class ResourceArtifact:
    value: ResourceModel
    sha256: str


@dataclass(frozen=True, slots=True)
class SecurityResources:
    system_prompt: ResourceArtifact
    baseline_prompt: ResourceArtifact
    guarded_prompt: ResourceArtifact
    guard_policy: ResourceArtifact
    detector: ResourceArtifact

    def artifact_digests(self) -> dict[str, str]:
        return {
            "system_prompt": self.system_prompt.sha256,
            "baseline_prompt_template": self.baseline_prompt.sha256,
            "guarded_prompt_template": self.guarded_prompt.sha256,
            "guard_policy": self.guard_policy.sha256,
            "detector": self.detector.sha256,
        }


_RESOURCE_MODELS: dict[str, type[ResourceModel]] = {
    "system-prompt.v1.yaml": SystemPromptResource,
    "baseline-prompt.v1.yaml": BaselinePromptResource,
    "guarded-prompt.v1.yaml": GuardedPromptResource,
    "guard-policy.v1.yaml": GuardPolicyResource,
    "detector.v1.yaml": DetectorResource,
}


def parse_resource_bytes(name: str, raw: bytes) -> ResourceArtifact:
    """Validate exact bytes without including their content in failures."""

    model_type = _RESOURCE_MODELS.get(name)
    if model_type is None or raw.startswith(codecs.BOM_UTF8) or b"\r" in raw:
        raise ResourceLoadError("resource_invalid")
    try:
        text = raw.decode("utf-8")
        payload = yaml.load(text, Loader=_UniqueKeySafeLoader)
        if not isinstance(payload, dict):
            raise ValueError
        value = model_type.model_validate(payload)
    except (UnicodeError, yaml.YAMLError, ValidationError, ValueError, TypeError):
        raise ResourceLoadError("resource_invalid") from None
    return ResourceArtifact(value=value, sha256=hashlib.sha256(raw).hexdigest())


def _package_reader(name: str) -> bytes:
    try:
        return resources.files(_RESOURCE_PACKAGE).joinpath(name).read_bytes()
    except (FileNotFoundError, ModuleNotFoundError, OSError, TypeError):
        raise ResourceLoadError("resource_unavailable") from None


def load_security_resources(
    reader: Callable[[str], bytes] | None = None,
) -> SecurityResources:
    """Explicitly read and validate every reviewed resource."""

    read = _package_reader if reader is None else reader
    loaded: dict[str, ResourceArtifact] = {}
    try:
        for name in RESOURCE_NAMES:
            loaded[name] = parse_resource_bytes(name, read(name))
    except ResourceLoadError:
        raise
    except (KeyError, OSError, TypeError, ValueError):
        raise ResourceLoadError("resource_unavailable") from None

    system = loaded["system-prompt.v1.yaml"].value
    if not isinstance(system, SystemPromptResource):
        raise ResourceLoadError("resource_invalid")
    marker = system.system_canary_literal
    for name in RESOURCE_NAMES[1:]:
        if marker in loaded[name].value.model_dump_json():
            raise ResourceLoadError("resource_invalid")

    return SecurityResources(
        system_prompt=loaded["system-prompt.v1.yaml"],
        baseline_prompt=loaded["baseline-prompt.v1.yaml"],
        guarded_prompt=loaded["guarded-prompt.v1.yaml"],
        guard_policy=loaded["guard-policy.v1.yaml"],
        detector=loaded["detector.v1.yaml"],
    )
