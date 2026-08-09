"""Deterministic baseline/guarded retrieval and message planning."""

from __future__ import annotations

import json
import math
import re
import string
from dataclasses import dataclass

from pydantic import ValidationError

from dataguard.domain import Corpus, Document, IdentityTable, Role
from dataguard.ollama import OllamaClient, OllamaHealthFacts, OllamaMessage
from dataguard.resources import ResourceArtifact, SecurityResources
from dataguard.resources.loader import (
    BaselinePromptResource,
    DetectorResource,
    GuardPolicyResource,
    GuardedPromptResource,
    SystemPromptResource,
)
from dataguard.vector_index import (
    RetrievalResult,
    ValidatedVectorIndex,
    VectorIndexError,
    retrieve,
)

from dataguard.rag.errors import RagPlanningErrorCode, raise_rag_error
from dataguard.rag.models import AuthorizationDenial, RagMode, RagPlan, _create_rag_plan


SYNTHETIC_VERSION = "synthetic-v1"
DOCUMENT_COUNT = 30
RETRIEVAL_TOP_K = 4
NUM_CTX = 8192
NUM_PREDICT = 512

_DATA_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SUBJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_RAW_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_QUERY_TOKEN = object()
_PLANNER_TOKEN = object()


@dataclass(frozen=True, slots=True, repr=False, init=False)
class QueryEmbedding:
    """Opaque immutable query vector bound to one probed embedding model."""

    _vector: tuple[float, ...]
    _model_tag: str
    _model_digest: str
    _dimensions: int

    def __init__(
        self,
        vector: tuple[float, ...],
        model_tag: str,
        model_digest: str,
        dimensions: int,
        *,
        _token: object,
    ) -> None:
        if _token is not _QUERY_TOKEN:
            raise TypeError("query embeddings are created only by embed_query")
        object.__setattr__(self, "_vector", vector)
        object.__setattr__(self, "_model_tag", model_tag)
        object.__setattr__(self, "_model_digest", model_digest)
        object.__setattr__(self, "_dimensions", dimensions)

    @property
    def dimensions(self) -> int:
        return self._dimensions

    @property
    def embedding_model_tag(self) -> str:
        return self._model_tag

    @property
    def embedding_model_digest(self) -> str:
        return self._model_digest

    def __repr__(self) -> str:
        return f"QueryEmbedding(dimensions={self._dimensions})"

    def _vector_for_planner(self, token: object) -> tuple[float, ...]:
        if token is not _PLANNER_TOKEN:
            raise TypeError("query vector access is restricted to the RAG planner")
        return self._vector


def _validate_question(question: object) -> str:
    if type(question) is not str or not 1 <= len(question) <= 2000:
        raise_rag_error(RagPlanningErrorCode.INVALID_REQUEST)
    try:
        question.encode("utf-8")
    except UnicodeEncodeError:
        raise_rag_error(RagPlanningErrorCode.INVALID_REQUEST)
    return question


async def embed_query(
    question: str,
    health: OllamaHealthFacts,
    client: OllamaClient,
) -> QueryEmbedding:
    """Embed the exact accepted question without retaining it in the handle."""

    accepted_question = _validate_question(question)
    if not isinstance(health, OllamaHealthFacts) or not isinstance(client, OllamaClient):
        raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
    try:
        health = OllamaHealthFacts.model_validate(
            health.model_dump(mode="python", warnings=False)
        )
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
    vectors = await client.embed(
        (accepted_question,), expected_dimensions=health.embedding_dimensions
    )
    if type(vectors) is not tuple or len(vectors) != 1:
        raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
    vector = vectors[0]
    if (
        type(vector) is not tuple
        or len(vector) != health.embedding_dimensions
        or any(type(value) not in {int, float} or not math.isfinite(value) for value in vector)
    ):
        raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
    converted = tuple(float(value) for value in vector)
    norm = math.hypot(*converted)
    if not math.isfinite(norm) or norm == 0.0:
        raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
    return QueryEmbedding(
        converted,
        health.embedding_model.tag,
        health.embedding_model.digest,
        health.embedding_dimensions,
        _token=_QUERY_TOKEN,
    )


def _render_reviewed_template(template: str, values: dict[str, str]) -> str:
    """Insert untrusted values once, without reparsing their braces as syntax."""

    rendered: list[str] = []
    try:
        for literal, field_name, format_spec, conversion in string.Formatter().parse(template):
            rendered.append(literal)
            if field_name is None:
                continue
            if format_spec or conversion or field_name not in values:
                raise ValueError
            rendered.append(values[field_name])
    except (KeyError, ValueError):
        raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
    return "".join(rendered)


def canonical_documents_json(documents: tuple[Document, ...]) -> str:
    if (
        type(documents) is not tuple
        or len(documents) != RETRIEVAL_TOP_K
        or any(type(document) is not Document for document in documents)
    ):
        raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
    try:
        validated = tuple(
            Document.model_validate(document.model_dump(mode="python", warnings=False))
            for document in documents
        )
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
    if len({document.doc_id for document in validated}) != RETRIEVAL_TOP_K:
        raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
    payload: list[dict[str, str]] = []
    for document in validated:
        payload.append(
            {
                "doc_id": document.doc_id,
                "title": document.title,
                "classification": document.classification.value,
                "content": document.content,
            }
        )
    try:
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, UnicodeError):
        raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)


def context_message_bytes(messages: tuple[OllamaMessage, ...]) -> int:
    if type(messages) is not tuple or not messages or any(
        not isinstance(message, OllamaMessage) for message in messages
    ):
        raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
    try:
        validated = tuple(
            OllamaMessage.model_validate(message.model_dump(mode="python", warnings=False))
            for message in messages
        )
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
    payload = [{"role": message.role, "content": message.content} for message in validated]
    try:
        return len(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        )
    except (TypeError, ValueError, UnicodeError):
        raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)


@dataclass(frozen=True, slots=True, repr=False, init=False)
class RagPlanner:
    _identities: IdentityTable
    _corpus: Corpus
    _corpus_sha256: str
    _resources: SecurityResources
    _index: ValidatedVectorIndex

    def __init__(
        self,
        identities: IdentityTable,
        corpus: Corpus,
        corpus_sha256: str,
        resources: SecurityResources,
        index: ValidatedVectorIndex,
        *,
        _token: object,
    ) -> None:
        if _token is not _PLANNER_TOKEN:
            raise TypeError("RAG planners are created only by create_rag_planner")
        object.__setattr__(self, "_identities", identities)
        object.__setattr__(self, "_corpus", corpus)
        object.__setattr__(self, "_corpus_sha256", corpus_sha256)
        object.__setattr__(self, "_resources", resources)
        object.__setattr__(self, "_index", index)

    def __repr__(self) -> str:
        return "RagPlanner(version='synthetic-v1', documents=30)"

    async def plan(
        self,
        *,
        corpus_version: str,
        subject_id: str,
        question: str,
        mode: str,
        query_embedding: QueryEmbedding,
    ) -> RagPlan:
        if type(corpus_version) is not str or _DATA_VERSION_PATTERN.fullmatch(corpus_version) is None:
            raise_rag_error(RagPlanningErrorCode.INVALID_REQUEST)
        if corpus_version != SYNTHETIC_VERSION:
            raise_rag_error(RagPlanningErrorCode.CORPUS_NOT_FOUND)
        if type(subject_id) is not str or _SUBJECT_ID_PATTERN.fullmatch(subject_id) is None:
            raise_rag_error(RagPlanningErrorCode.INVALID_REQUEST)
        role = self._identities.role_for(subject_id)
        if role is None:
            raise_rag_error(RagPlanningErrorCode.SUBJECT_NOT_FOUND)
        accepted_question = _validate_question(question)
        if type(mode) is not str or mode not in {item.value for item in RagMode}:
            raise_rag_error(RagPlanningErrorCode.INVALID_REQUEST)
        if not isinstance(query_embedding, QueryEmbedding):
            raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
        if (
            query_embedding.embedding_model_tag != self._index.embedding_model_tag
            or query_embedding.embedding_model_digest != self._index.embedding_model_digest
            or query_embedding.dimensions != self._index.dimensions
        ):
            raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)

        resolved_mode = RagMode(mode)
        if resolved_mode is RagMode.BASELINE:
            eligible = tuple(document.doc_id for document in self._corpus.documents)
            denials: tuple[AuthorizationDenial, ...] = ()
        else:
            eligible = tuple(
                document.doc_id
                for document in self._corpus.documents
                if role in document.allowed_roles
            )
            denials = tuple(
                AuthorizationDenial(doc_id=document.doc_id, reason="role_not_allowed")
                for document in self._corpus.documents
                if role not in document.allowed_roles
            )

        try:
            results = retrieve(
                self._index,
                query_embedding._vector_for_planner(_PLANNER_TOKEN),
                eligible,
            )
        except VectorIndexError:
            raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
        if type(results) is not tuple or len(results) != RETRIEVAL_TOP_K:
            raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
        try:
            results = tuple(
                RetrievalResult.model_validate(
                    result.model_dump(mode="python", warnings=False)
                )
                for result in results
            )
        except (AttributeError, TypeError, ValueError, ValidationError):
            raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
        result_ids = tuple(result.doc_id for result in results)
        if len(set(result_ids)) != RETRIEVAL_TOP_K or not set(result_ids).issubset(eligible):
            raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
        documents_by_id = {document.doc_id: document for document in self._corpus.documents}
        try:
            selected = tuple(documents_by_id[doc_id] for doc_id in result_ids)
        except KeyError:
            raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
        documents_json = canonical_documents_json(selected)
        messages = self._messages(resolved_mode, accepted_question, documents_json)
        message_bytes = context_message_bytes(messages)
        if message_bytes + NUM_PREDICT > NUM_CTX:
            raise_rag_error(RagPlanningErrorCode.CONTEXT_BUDGET_EXCEEDED)
        return _create_rag_plan(
            mode=resolved_mode,
            resolved_role=role,
            retrieval_results=results,
            authorization_denials=denials,
            messages=messages,
            context_message_bytes=message_bytes,
        )

    def _messages(
        self,
        mode: RagMode,
        question: str,
        documents_json: str,
    ) -> tuple[OllamaMessage, ...]:
        system = self._resources.system_prompt.value
        if not isinstance(system, SystemPromptResource):
            raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
        if mode is RagMode.BASELINE:
            template = self._resources.baseline_prompt.value
            if not isinstance(template, BaselinePromptResource):
                raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
            content = _render_reviewed_template(
                template.template,
                {
                    "system_prompt": system.content,
                    "documents_text": documents_json,
                    "question": question,
                },
            )
            try:
                return (OllamaMessage(role="user", content=content),)
            except ValidationError:
                raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)

        template = self._resources.guarded_prompt.value
        if not isinstance(template, GuardedPromptResource):
            raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
        values = {
            "system_prompt": system.content,
            "documents_json": documents_json,
            "question": question,
        }
        try:
            return tuple(
                OllamaMessage(
                    role=message.role,
                    content=_render_reviewed_template(message.template, values),
                )
                for message in template.messages
            )
        except ValidationError:
            raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)


def create_rag_planner(
    identities: IdentityTable,
    corpus: Corpus,
    corpus_sha256: str,
    resources: SecurityResources,
    index: ValidatedVectorIndex,
) -> RagPlanner:
    """Bind accepted fixtures, reviewed resources, and the validated index."""

    try:
        if not isinstance(identities, IdentityTable) or not isinstance(corpus, Corpus):
            raise ValueError
        identities = IdentityTable.model_validate(identities.model_dump(mode="python"))
        corpus = Corpus.model_validate(corpus.model_dump(mode="python"))
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
    identity_ids = tuple(identity.subject_id for identity in identities.identities)
    document_ids = tuple(document.doc_id for document in corpus.documents)
    if (
        type(corpus_sha256) is not str
        or _RAW_SHA256_PATTERN.fullmatch(corpus_sha256) is None
        or type(resources) is not SecurityResources
        or not isinstance(index, ValidatedVectorIndex)
        or identities.version != corpus.identity_table_version
        or corpus.corpus_version != SYNTHETIC_VERSION
        or len(identity_ids) != 6
        or len(set(identity_ids)) != 6
        or len(document_ids) != DOCUMENT_COUNT
        or len(set(document_ids)) != DOCUMENT_COUNT
        or index.document_count != DOCUMENT_COUNT
        or index.corpus_sha256 != corpus_sha256
        or index.ordered_document_ids != document_ids
    ):
        raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
    resource_artifacts = (
        resources.system_prompt,
        resources.baseline_prompt,
        resources.guarded_prompt,
        resources.guard_policy,
        resources.detector,
    )
    resource_types = (
        SystemPromptResource,
        BaselinePromptResource,
        GuardedPromptResource,
        GuardPolicyResource,
        DetectorResource,
    )
    validated_values: list[
        SystemPromptResource
        | BaselinePromptResource
        | GuardedPromptResource
        | GuardPolicyResource
        | DetectorResource
    ] = []
    try:
        for artifact, expected_type in zip(resource_artifacts, resource_types, strict=True):
            if (
                type(artifact) is not ResourceArtifact
                or not isinstance(artifact.value, expected_type)
                or type(artifact.sha256) is not str
                or _RAW_SHA256_PATTERN.fullmatch(artifact.sha256) is None
            ):
                raise ValueError
            validated_values.append(
                expected_type.model_validate(
                    artifact.value.model_dump(mode="python", warnings=False)
                )
            )
    except (AttributeError, TypeError, ValueError, ValidationError):
        raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
    resource_values = tuple(validated_values)
    evidence_ids = {
        canary.canary_id
        for document in corpus.documents
        for canary in document.canaries
    } | {
        fragment.fragment_id
        for document in corpus.documents
        for fragment in document.protected_fragments
    }
    system_resource = resource_values[0]
    if not isinstance(system_resource, SystemPromptResource):
        raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
    system_marker = system_resource.system_canary_literal
    if (
        str(system_resource.system_canary_evidence_id) in evidence_ids
        or any(
            system_marker in resource.model_dump_json()
            for resource in resource_values[1:]
        )
    ):
        raise_rag_error(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
    validated_resources = SecurityResources(
        system_prompt=ResourceArtifact(
            value=resource_values[0], sha256=resource_artifacts[0].sha256
        ),
        baseline_prompt=ResourceArtifact(
            value=resource_values[1], sha256=resource_artifacts[1].sha256
        ),
        guarded_prompt=ResourceArtifact(
            value=resource_values[2], sha256=resource_artifacts[2].sha256
        ),
        guard_policy=ResourceArtifact(
            value=resource_values[3], sha256=resource_artifacts[3].sha256
        ),
        detector=ResourceArtifact(
            value=resource_values[4], sha256=resource_artifacts[4].sha256
        ),
    )
    return RagPlanner(
        identities,
        corpus,
        corpus_sha256,
        validated_resources,
        index,
        _token=_PLANNER_TOKEN,
    )
