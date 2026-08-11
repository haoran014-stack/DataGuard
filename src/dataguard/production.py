"""Explicit production composition and six-endpoint application services."""

from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

import httpx

from dataguard.api import create_app
from dataguard.api.models import (
    ChatResponse, EvaluationRunRequest, HealthReason, HealthResponse, HealthStatus,
    ModelHealth, OllamaHealth, StorageHealth,
)
from dataguard.api.reports import ReportContract
from dataguard.config import RuntimeProfile, RuntimeSettings, StorageBackend
from dataguard.detector import build_whole_output_detector
from dataguard.evaluation import (
    EvaluationScheduleError, create_evaluation_context, create_evaluation_runner,
    create_evaluation_scheduler,
)
from dataguard.evaluation.models import Judgment, ScenarioEvidence
from dataguard.metrics import MetricsError, MetricsRegistry, load_metrics_contract
from dataguard.ollama import OllamaClient, OllamaHealthFacts
from dataguard.rag import create_rag_executor, create_rag_planner, embed_query
from dataguard.resources import load_security_resources
from dataguard.storage import (
    AuditEvent, AuditEventFilter, AuditEventPage,
    AuditEventType, AuditOutcome, AuthorizationDenial, DetectionEvidence,
    ErrorCode, EvaluationProfile, EvaluationRun, RetrievedDocumentEvidence, StoredReport,
    StorageError, create_audit_repository,
)
from dataguard.validation import load_fixture_bundle
from dataguard.vector_index import (
    StoredIndexFacts, VectorIndexStore, VectorIndexStoreError,
    VectorIndexError,
    create_loaded_vector_index, load_canonical_vector_index,
    validate_vector_index_binding, vector_index_sha256,
)


class ProductionError(Exception):
    __slots__ = ("_code",)

    def __init__(self, code: str = "internal_error") -> None:
        try: safe = ErrorCode(code).value
        except (ValueError, TypeError): safe = ErrorCode.INTERNAL_ERROR.value
        object.__setattr__(self, "_code", safe)
        super().__init__("DataGuard production services are unavailable.")

    @property
    def code(self) -> str:
        return self._code

    def __setattr__(self, name: str, value: object) -> None:
        if name in {"__traceback__", "__cause__", "__context__", "__suppress_context__"}:
            return super().__setattr__(name, value)
        raise AttributeError("production errors are fixed")

    def __repr__(self) -> str:
        return f"ProductionError(code={self.code!r})"


class _Clock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)

    def monotonic_ns(self) -> int:
        return time.monotonic_ns()


class _ProductionScenarioSink:
    """Persist and aggregate only the controlled minimized A7a projection."""

    __slots__ = ("_repository", "_metrics", "_backend")

    def __init__(self, repository: Any, metrics: MetricsRegistry, backend: str) -> None:
        self._repository = repository
        self._metrics = metrics
        self._backend = backend

    def _increment(self, name: str, labels: dict[str, str], amount: int = 1) -> None:
        try: self._metrics.increment(name, labels, amount)
        except Exception: pass

    def record_scenario(self, run_id: str, evidence: ScenarioEvidence) -> None:
        if type(evidence) is not ScenarioEvidence:
            raise ProductionError("internal_error")
        attack = evidence.family.value != "authorized_qa"
        events = []
        for mode_name, mode in (("baseline", evidence.baseline), ("guarded", evidence.guarded)):
            events.append(AuditEvent(event_id=str(uuid4()),
                event_type=AuditEventType.OUTPUT_DETECTION_COMPLETED,
                occurred_at=datetime.now(timezone.utc), trace_id=mode.trace_id,
                run_id=run_id, subject_id=evidence.subject_id,
                resolved_role=evidence.resolved_role, mode=mode_name,
                outcome=AuditOutcome(mode.outcome.value), corpus_version="synthetic-v1",
                retrieved_documents=mode.retrieval_evidence,
                authorization_denials=mode.authorization_denials,
                detections=mode.detections, error_code=mode.error_code))
        try:
            for event in events:
                self._repository.append_event(event)
        except Exception:
            self._increment("dataguard_evidence_write_failures_total",
                {"backend": self._backend, "record_type": "audit_event"})
            raise StorageError() from None

        for mode_name, mode in (("baseline", evidence.baseline), ("guarded", evidence.guarded)):
            for item in mode.retrieval_evidence:
                if item.included_in_context:
                    self._increment("dataguard_retrieved_documents_total", {"mode": mode_name,
                        "authorization": "authorized" if item.authorized else "unauthorized"})
            for item in mode.detections:
                self._increment("dataguard_output_detector_matches_total", {"mode": mode_name,
                    "detection_type": item.type.value, "detector_action": item.action.value})
            unauthorized = sum(not item.authorized and item.included_in_context
                               for item in mode.retrieval_evidence)
            self._increment("dataguard_unauthorized_context_documents_total",
                {"mode": mode_name}, unauthorized)
            kind = "attack" if attack else "authorized_qa"
            self._increment("dataguard_scenario_judgments_total",
                {"mode": mode_name, "scenario_kind": kind, "judgment": mode.judgment.value})
            if attack:
                self._increment("dataguard_attack_attempts_total",
                    {"mode": mode_name, "attack_family": evidence.family.value})
                if mode.final_leak_count > 0:
                    self._increment("dataguard_attack_successes_total",
                        {"mode": mode_name, "attack_family": evidence.family.value})
                if mode.attack_delivered:
                    self._increment("dataguard_attack_deliveries_total",
                        {"mode": mode_name, "attack_family": evidence.family.value})
                if evidence.family.value == "cross_role_retrieval" and unauthorized:
                    self._increment("dataguard_retrieval_authorization_violation_scenarios_total",
                        {"mode": mode_name})
            else:
                result = ("indeterminate" if mode.judgment is Judgment.INDETERMINATE else
                    "false_rejection" if mode.judgment is Judgment.FALSE_REJECTION else
                    "pass" if mode.judgment is Judgment.AUTHORIZED_QA_PASS else "fail")
                self._increment("dataguard_authorized_qa_results_total",
                    {"mode": mode_name, "result": result})
        if evidence.prevention_stage is not None:
            self._increment("dataguard_blocked_baseline_attacks_total", {})
            self._increment("dataguard_guard_interventions_total",
                {"prevention_stage": evidence.prevention_stage.value})


class _ProductionOperationSink:
    __slots__ = ("_metrics", "_backend", "_started")

    def __init__(self, metrics: MetricsRegistry, backend: str) -> None:
        self._metrics = metrics
        self._backend = backend
        self._started: dict[str, tuple[str, float]] = {}

    def record_operation(self, operation: str, result: str) -> None:
        try:
            self._metrics.increment("dataguard_ollama_requests_total",
                                    {"operation": operation, "result": result})
        except Exception:
            pass

    def record_run_started(self, run_id: str, profile: str) -> None:
        if len(self._started) >= 64 or run_id in self._started:
            return
        self._started[run_id] = (profile, time.monotonic())
        try:
            self._metrics.increment("dataguard_evaluation_runs_total", {
                "profile": profile, "status": "running", "storage_backend": self._backend})
        except Exception:
            pass

    def record_terminal(self, run: EvaluationRun) -> None:
        started = self._started.pop(run.run_id, None)
        try:
            self._metrics.increment("dataguard_evaluation_runs_total", {
                "profile": run.profile.value, "status": run.status.value,
                "storage_backend": self._backend})
            if started is not None:
                self._metrics.observe("dataguard_evaluation_run_duration_seconds", {
                    "profile": run.profile.value, "terminal_status": run.status.value},
                    max(0.0, time.monotonic() - started[1]))
        except Exception:
            pass

    def clear(self) -> None:
        self._started.clear()


class _RuntimeReportContract(ReportContract):
    """Side-effect-free proxy whose backing contract is installed at startup."""

    __slots__ = ("_runtime",)

    def __init__(self, runtime: "ProductionRuntime") -> None:
        self._runtime = runtime

    def validate(self, stored: StoredReport):
        contract = self._runtime._report_contract
        if contract is None:
            raise ValueError("stored report validation is unavailable")
        return contract.validate(stored)

    def __repr__(self) -> str:
        return "RuntimeReportContract()"


def _read_json(path: Path, limit: int = 2 * 1024 * 1024) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        if len(raw) > limit or raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw:
            raise ValueError
        value = json.loads(raw.decode("utf-8"))
        if type(value) is not dict:
            raise ValueError
        return value
    except Exception:
        raise ProductionError() from None


def _manifest(bundle, resources, loaded, health: OllamaHealthFacts,
              settings: RuntimeSettings, created_at: str) -> dict[str, Any]:
    digests = resources.artifact_digests()
    policy = resources.guard_policy.value
    detector = resources.detector.value
    system = resources.system_prompt.value
    return {
        "manifest_version": "1.0", "synthetic": True,
        "corpus_version": "synthetic-v1", "scenario_set_version": "synthetic-v1",
        "created_at": created_at, "profile": settings.profile.value,
        "storage_backend": settings.storage_backend.value,
        "distribution": {
            "identities": {"total": 6, "by_role": {"guest": 2, "employee": 2, "security_reviewer": 2}},
            "documents": {"total": 30, "by_classification_and_language": {
                name: {"total": 10, "en": 5, "zh": 5}
                for name in ("public", "internal", "confidential")}},
            "scenarios": {"total": 62,
                "authorized_qa": {"total": 30, "one_per_document": True},
                "attacks": {"total": 32, "by_family": {
                    name: {"total": 8, "en": 4, "zh": 4}
                    for name in ("direct_prompt_injection", "indirect_document_injection",
                                 "cross_role_retrieval", "system_prompt_inducement")}}},
        },
        "models": {"ollama_version": health.version,
            "generation": {"tag": health.generation_model.tag, "digest": health.generation_model.digest},
            "embedding": {"tag": health.embedding_model.tag, "digest": health.embedding_model.digest,
                          "embedding_dimensions": health.embedding_dimensions}},
        "settings": policy.settings.model_dump(mode="json"),
        "system_prompt": {"system_canary_evidence_id": str(system.system_canary_evidence_id),
                          "content_digest": resources.system_prompt.sha256},
        "detector": {"version": detector.version, "normalization": list(detector.normalization),
                     "detection_types": list(detector.detection_types),
                     "guarded_block_reply": detector.guarded_fixed_reply},
        "artifact_digests": {"identity_table": bundle.identity_sha256,
            "corpus": bundle.corpus_sha256, "scenario_set": bundle.scenario_sha256,
            "vector_index": loaded.facts.artifact_sha256,
            "baseline_prompt_template": digests["baseline_prompt_template"],
            "guarded_prompt_template": digests["guarded_prompt_template"],
            "guard_policy": digests["guard_policy"], "detector": digests["detector"]},
    }


@dataclass(frozen=True, slots=True, repr=False, init=False)
class ProductionRuntime:
    _project_root: Path
    _settings_input: RuntimeSettings
    _manifest_input: Mapping[str, Any] | None
    _transport: httpx.AsyncBaseTransport | None
    _started: bool
    _closed: bool
    _repository: Any
    _client: OllamaClient | None
    _scheduler: Any
    _services_ready: bool
    _ready_error_code: str
    _health: HealthResponse | None
    _report_contract: ReportContract | None
    _metrics: MetricsRegistry | None
    _planner: Any
    _executor: Any
    _context: Any
    _run_metrics: Any

    def __init__(self, project_root: Path, settings: RuntimeSettings,
                 manifest: Mapping[str, Any] | None,
                 transport: httpx.AsyncBaseTransport | None) -> None:
        object.__setattr__(self, "_project_root", project_root)
        object.__setattr__(self, "_settings_input", settings)
        object.__setattr__(self, "_manifest_input", manifest)
        object.__setattr__(self, "_transport", transport)
        for name, value in (("_started", False), ("_closed", False), ("_repository", None),
            ("_client", None), ("_scheduler", None), ("_services_ready", False),
            ("_ready_error_code", "internal_error"),
            ("_health", None), ("_report_contract", None), ("_metrics", None),
            ("_planner", None), ("_executor", None), ("_context", None),
            ("_run_metrics", None)):
            object.__setattr__(self, name, value)

    def __repr__(self) -> str:
        return f"ProductionRuntime(started={self._started}, ready={self._services_ready})"

    async def startup(self) -> None:
        if self._started or self._closed:
            raise ProductionError()
        repository = None
        client = None
        try:
            settings = RuntimeSettings.model_validate({**self._settings_input.model_dump(mode="python"),
                "database_dsn": self._settings_input.database_dsn_value()})
            loaded_bundle = load_fixture_bundle(self._project_root)
            if not loaded_bundle.ok or loaded_bundle.bundle is None:
                raise ProductionError("experiment_manifest_mismatch")
            bundle = loaded_bundle.bundle
            resources = load_security_resources()
            report_schema = _read_json(self._project_root / "docs/contracts/report.schema.json")
            manifest_schema = _read_json(self._project_root / "docs/contracts/experiment-manifest.schema.json")
            metrics_raw = (self._project_root / "docs/contracts/metrics.yaml").read_bytes()
            if metrics_raw.startswith(b"\xef\xbb\xbf") or b"\r" in metrics_raw:
                raise ProductionError()
            metrics = MetricsRegistry(load_metrics_contract(metrics_raw))

            storage_error = False
            try:
                repository = create_audit_repository(settings, self._project_root)
                repository.prepare_schema()
                repository.recover_interrupted_runs(datetime.now(timezone.utc))
            except Exception:
                storage_error = True
                if repository is not None:
                    try: repository.close()
                    except Exception: pass
                    repository = None

            store = VectorIndexStore(self._project_root, settings)
            index_artifact = None
            index_state = None
            try:
                raw_index = store.read()
                index_artifact = load_canonical_vector_index(raw_index)
            except VectorIndexStoreError as error:
                index_state = error.state.value
            except VectorIndexError:
                index_state = "corrupt"
            client = OllamaClient(settings, transport=self._transport)
            health = None
            ollama_error = None
            try:
                health = await client.probe()
            except Exception as error:
                code = getattr(getattr(error, "code", None), "value", None)
                ollama_error = code if type(code) is str else "ollama_unavailable"
            loaded_index = None
            if index_artifact is not None and health is not None:
                try:
                    validated = validate_vector_index_binding(index_artifact, bundle.corpus,
                        bundle.corpus_sha256, health)
                    loaded_index = create_loaded_vector_index(validated, StoredIndexFacts(
                        artifact_sha256=vector_index_sha256(raw_index), format=index_artifact.format,
                        document_count=len(index_artifact.entries), dimensions=index_artifact.dimensions))
                except Exception:
                    index_state = "stale"

            ready = loaded_index is not None and repository is not None and health is not None
            reasons: list[HealthReason] = []
            if index_artifact is None or (index_artifact is not None and health is not None and loaded_index is None):
                reasons.append(HealthReason.EXPERIMENT_MANIFEST_MISMATCH)
            if storage_error:
                reasons.append(HealthReason.STORAGE_UNAVAILABLE)
            if ollama_error is not None:
                try: reasons.append(HealthReason(ollama_error))
                except ValueError: reasons.append(HealthReason.OLLAMA_UNAVAILABLE)
            if settings.storage_backend is not StorageBackend.POSTGRESQL:
                reasons.append(HealthReason.STORAGE_NOT_POSTGRESQL)
            checked = datetime.now(timezone.utc)
            dependency_down = storage_error or health is None
            cached_health = HealthResponse(status=(HealthStatus.UNHEALTHY if dependency_down else
                HealthStatus.HEALTHY if not reasons else HealthStatus.DEGRADED),
                api_version="v1", ollama=OllamaHealth(status="down" if health is None else "up",
                    version=None if health is None else health.version,
                    generation_model=ModelHealth(tag="qwen2.5:3b-instruct",
                        digest=None if health is None else health.generation_model.digest,
                        available=health is not None),
                    embedding_model=ModelHealth(tag="qwen3-embedding:0.6b",
                        digest=None if health is None else health.embedding_model.digest,
                        available=health is not None)),
                storage=StorageHealth(status="down" if storage_error else "up",
                    backend="unavailable" if storage_error else settings.storage_backend.value),
                evidence_readiness=not reasons, reasons=tuple(reasons), checked_at=checked)

            report_contract = ReportContract(report_schema)
            context = planner = executor = scheduler = run_metrics = None
            if ready:
                if settings.profile is RuntimeProfile.EVIDENCE and self._manifest_input is None:
                    raise ProductionError("experiment_manifest_mismatch")
                manifest = (dict(self._manifest_input) if self._manifest_input is not None else
                    _manifest(bundle, resources, loaded_index, health, settings,
                              checked.isoformat().replace("+00:00", "Z")))
                context = create_evaluation_context(bundle, resources, loaded_index, health,
                    settings, manifest, report_schema, manifest_schema)
                planner = create_rag_planner(bundle.identities, bundle.corpus,
                    bundle.corpus_sha256, resources, context.loaded_index.validated_index)
                detector = build_whole_output_detector(resources, bundle.corpus)
                executor = create_rag_executor(client, detector)
                run_metrics = _ProductionOperationSink(metrics, settings.storage_backend.value)
                runner = create_evaluation_runner(context, planner, executor, repository,
                    _Clock(), lambda: str(uuid4()),
                    _ProductionScenarioSink(repository, metrics, settings.storage_backend.value),
                    run_metrics)
                scheduler = create_evaluation_scheduler(runner)
            object.__setattr__(self, "_repository", repository)
            object.__setattr__(self, "_client", client)
            object.__setattr__(self, "_scheduler", scheduler)
            object.__setattr__(self, "_services_ready", ready)
            ready_error = ("storage_unavailable" if storage_error else ollama_error
                if ollama_error is not None else "experiment_manifest_mismatch")
            object.__setattr__(self, "_ready_error_code", ready_error)
            object.__setattr__(self, "_health", cached_health)
            object.__setattr__(self, "_report_contract", report_contract)
            object.__setattr__(self, "_metrics", metrics)
            object.__setattr__(self, "_planner", planner)
            object.__setattr__(self, "_executor", executor)
            object.__setattr__(self, "_context", context)
            object.__setattr__(self, "_run_metrics", run_metrics)
            object.__setattr__(self, "_started", True)
        except Exception as error:
            if client is not None:
                try: await client.aclose()
                except Exception: pass
            if repository is not None:
                try: repository.close()
                except Exception: pass
            if isinstance(error, ProductionError): raise
            code = getattr(getattr(error, "code", None), "value", getattr(error, "code", "internal_error"))
            raise ProductionError(code if type(code) is str else "internal_error") from None

    async def shutdown(self) -> None:
        if self._closed:
            return
        object.__setattr__(self, "_closed", True)
        failure = False
        try:
            if self._scheduler is not None:
                await self._scheduler.shutdown()
        except Exception:
            failure = True
        finally:
            if self._client is not None:
                try: await self._client.aclose()
                except Exception: failure = True
            if self._repository is not None:
                try: self._repository.close()
                except Exception: failure = True
            if self._run_metrics is not None:
                self._run_metrics.clear()
            object.__setattr__(self, "_started", False)
        if failure:
            raise ProductionError()

    def _require_started(self, *, ready: bool = False) -> None:
        if not self._started or self._closed or (ready and not self._services_ready):
            raise ProductionError(self._ready_error_code if self._started and ready else "internal_error")

    def _metric(self, operation: str, *args: Any) -> None:
        try:
            getattr(self._metrics, operation)(*args)
        except (MetricsError, AttributeError, TypeError, ValueError):
            pass

    async def chat(self, request) -> ChatResponse:
        self._require_started(ready=True)
        trace = str(uuid4())
        started = time.monotonic()
        try:
            query = await embed_query(request.question, self._context.health, self._executor._client)
        except Exception as error:
            self._record_ollama_error("embedding", error)
            raise
        self._metric("increment", "dataguard_ollama_requests_total",
                     {"operation": "embedding", "result": "success"})
        plan = await self._planner.plan(corpus_version=request.corpus_version,
            subject_id=request.subject_id, question=request.question,
            mode=request.mode.value, query_embedding=query)
        try:
            result = await self._executor.execute(plan)
        except Exception as error:
            self._record_ollama_error("generation", error)
            raise
        self._metric("increment", "dataguard_ollama_requests_total",
                     {"operation": "generation", "result": "success"})
        documents = {d.doc_id: d for d in self._context.bundle.corpus.documents}
        retrieved = tuple(RetrievedDocumentEvidence(document_id=item.doc_id, rank=index,
            similarity_score=item.similarity_score,
            authorized=plan.resolved_role in documents[item.doc_id].allowed_roles,
            included_in_context=True, denial_reason=None)
            for index, item in enumerate(plan.retrieval_results, 1))
        denials = tuple(AuthorizationDenial(document_id=item.doc_id, reason=item.reason)
                        for item in plan.authorization_denials)
        detections = tuple(DetectionEvidence.model_validate(item.model_dump(mode="python"))
                           for item in result.detections)
        event = AuditEvent(event_id=str(uuid4()), event_type=AuditEventType.CHAT_COMPLETED,
            occurred_at=datetime.now(timezone.utc), trace_id=trace,
            subject_id=request.subject_id, resolved_role=plan.resolved_role, mode=plan.mode,
            outcome=AuditOutcome(result.outcome.value), corpus_version=request.corpus_version,
            retrieved_documents=retrieved, authorization_denials=denials,
            detections=detections, error_code=None)
        try:
            self._repository.append_event(event)
        except Exception:
            self._metric("increment", "dataguard_evidence_write_failures_total",
                {"backend": self._context.settings.storage_backend.value,
                 "record_type": "audit_event"})
            raise ProductionError("storage_unavailable") from None
        outcome = result.outcome.value
        for item in retrieved:
            self._metric("increment", "dataguard_retrieved_documents_total", {"mode": plan.mode.value,
                "authorization": "authorized" if item.authorized else "unauthorized"})
        for item in detections:
            self._metric("increment", "dataguard_output_detector_matches_total", {
                "mode": plan.mode.value, "detection_type": item.type.value,
                "detector_action": item.action.value})
        unauthorized = sum(not item.authorized and item.included_in_context for item in retrieved)
        self._metric("increment", "dataguard_unauthorized_context_documents_total",
                     {"mode": plan.mode.value}, unauthorized)
        if plan.mode.value == "guarded" and outcome == "blocked":
            self._metric("increment", "dataguard_guard_interventions_total",
                         {"prevention_stage": "output_gate"})
        self._metric("increment", "dataguard_chat_requests_total",
            {"mode": plan.mode.value, "resolved_role": plan.resolved_role.value, "outcome": outcome})
        self._metric("observe", "dataguard_chat_duration_seconds",
            {"mode": plan.mode.value, "outcome": outcome}, time.monotonic() - started)
        return ChatResponse(reply=result.reply, trace_id=trace, outcome=outcome)

    def _record_ollama_error(self, operation: str, error: Exception) -> None:
        code = getattr(getattr(error, "code", None), "value", getattr(error, "code", None))
        result = ("timeout" if code == "model_timeout" else "unavailable"
            if code in {"ollama_unavailable", "generation_model_unavailable",
                        "embedding_model_unavailable"} else "protocol_error")
        self._metric("increment", "dataguard_ollama_requests_total",
                     {"operation": operation, "result": result})

    async def create_run(self, request: EvaluationRunRequest) -> EvaluationRun:
        self._require_started(ready=True)
        if request.scenario_set_version != "synthetic-v1" \
                or request.profile.value != self._context.settings.profile.value:
            raise ProductionError("experiment_manifest_mismatch")
        try:
            reservation = self._scheduler.reserve()
        except EvaluationScheduleError:
            raise ProductionError() from None
        try:
            run = self._repository.create_run(request.scenario_set_version,
                EvaluationProfile(request.profile.value), datetime.now(timezone.utc))
        except Exception:
            self._scheduler.release(reservation)
            raise
        task = self._scheduler.commit(reservation, run.run_id)
        task.add_done_callback(lambda completed, run_id=run.run_id:
                               self._evaluation_done(completed, run_id))
        try:
            self._repository.append_event(AuditEvent(event_id=str(uuid4()),
                event_type=AuditEventType.RUN_CREATED, occurred_at=datetime.now(timezone.utc),
                run_id=run.run_id, outcome=AuditOutcome.QUEUED))
        except Exception:
            self._metric("increment", "dataguard_evidence_write_failures_total",
                {"backend": self._context.settings.storage_backend.value,
                 "record_type": "audit_event"})
        self._metric("increment", "dataguard_evaluation_runs_total",
            {"profile": run.profile.value, "status": "queued",
             "storage_backend": self._context.settings.storage_backend.value})
        return run

    def _evaluation_done(self, task, run_id: str) -> None:
        try:
            try:
                run = task.result()
            except BaseException:
                run = self._repository.get_run(run_id)
            if run.status.value not in {"completed", "failed", "interrupted"}:
                return
        except BaseException:
            return
        try:
            self._repository.append_event(AuditEvent(event_id=str(uuid4()),
                event_type=AuditEventType.RUN_STATE_CHANGED,
                occurred_at=datetime.now(timezone.utc), run_id=run_id,
                outcome=AuditOutcome(run.status.value), error_code=run.failure_code))
        except BaseException:
            self._metric("increment", "dataguard_evidence_write_failures_total",
                {"backend": self._context.settings.storage_backend.value,
                 "record_type": "audit_event"})
        finally:
            self._run_metrics.record_terminal(run)

    async def get_run(self, run_id: str) -> EvaluationRun:
        self._require_started()
        if self._repository is None: raise ProductionError("storage_unavailable")
        return self._repository.get_run(run_id)

    async def list_audit(self, filters: AuditEventFilter) -> AuditEventPage:
        self._require_started()
        if self._repository is None: raise ProductionError("storage_unavailable")
        return self._repository.list_events(filters)

    async def get_report(self, run_id: str) -> StoredReport:
        self._require_started()
        if self._repository is None: raise ProductionError("storage_unavailable")
        return self._repository.get_report(run_id)

    async def health(self) -> HealthResponse:
        self._require_started(); return self._health

    def render_metrics(self) -> str:
        self._require_started(); return self._metrics.render_prometheus()


def create_runtime(project_root: Path, settings: RuntimeSettings,
                   *, manifest: Mapping[str, Any] | None = None,
                   transport: httpx.AsyncBaseTransport | None = None) -> ProductionRuntime:
    if not isinstance(project_root, Path) or not project_root.is_absolute() \
            or type(settings) is not RuntimeSettings:
        raise ProductionError()
    return ProductionRuntime(project_root, settings, manifest, transport)


def create_production_app(runtime: ProductionRuntime):
    if type(runtime) is not ProductionRuntime:
        raise ProductionError()
    @asynccontextmanager
    async def lifespan(_app):
        await runtime.startup()
        try:
            yield
        finally:
            await runtime.shutdown()
    return create_app(runtime, _RuntimeReportContract(runtime), lifespan=lifespan)
