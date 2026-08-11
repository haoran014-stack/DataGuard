from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import httpx
import pytest

import dataguard.production as production_module
from dataguard.api.models import ChatRequest, EvaluationRunRequest
from dataguard.config import RuntimeSettings
from dataguard.production import ProductionError, create_production_app, create_runtime
from dataguard.storage import (
    AuditEventFilter, EvaluationProfile, StorageError, create_audit_repository,
)
from dataguard.validation import load_fixture_bundle
from dataguard.vector_index import (
    VECTOR_INDEX_FORMAT, VectorIndexArtifact, VectorIndexEntry, VectorIndexStore,
)


ROOT = Path(__file__).resolve().parents[2]
GENERATION_DIGEST = "a" * 64
EMBEDDING_DIGEST = "sha256:" + "b" * 64
DIMENSIONS = 3


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    (root / "docs").mkdir(parents=True)
    shutil.copytree(ROOT / "data", root / "data")
    shutil.copytree(ROOT / "docs/contracts", root / "docs/contracts")
    return root


def _settings() -> RuntimeSettings:
    return RuntimeSettings(runtime_state_dir="artifacts/runtime",
        database_dsn="sqlite+pysqlite:///artifacts/runtime/dataguard.sqlite3")


def _write_index(root: Path, settings: RuntimeSettings, *, embedding_digest: str = EMBEDDING_DIGEST) -> None:
    loaded = load_fixture_bundle(root)
    assert loaded.ok and loaded.bundle is not None
    bundle = loaded.bundle
    ids = tuple(document.doc_id for document in bundle.corpus.documents)
    artifact = VectorIndexArtifact(format=VECTOR_INDEX_FORMAT,
        corpus_version=bundle.corpus.corpus_version, corpus_sha256=bundle.corpus_sha256,
        ordered_document_ids=ids, embedding_model_tag="qwen3-embedding:0.6b",
        embedding_model_digest=embedding_digest, dimensions=DIMENSIONS,
        entries=tuple(VectorIndexEntry(doc_id=doc_id,
            vector=(1.0, float(index + 1), -1.0)) for index, doc_id in enumerate(ids)))
    VectorIndexStore(root, settings).write(artifact)


def _transport(calls: list[tuple[str, str, object]]) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content) if request.content else None
        calls.append((request.method, request.url.path, payload))
        headers = {"Content-Type": "application/json"}
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.12.1"}, headers=headers)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [
                {"name": "qwen2.5:3b-instruct", "model": "qwen2.5:3b-instruct",
                 "digest": GENERATION_DIGEST},
                {"name": "qwen3-embedding:0.6b", "model": "qwen3-embedding:0.6b",
                 "digest": EMBEDDING_DIGEST},
            ]}, headers=headers)
        if request.url.path == "/api/show":
            return httpx.Response(200, json={
                "model_info": {"synthetic.embedding_length": DIMENSIONS}}, headers=headers)
        if request.url.path == "/api/embed":
            return httpx.Response(200, json={"model": "qwen3-embedding:0.6b",
                "embeddings": [[1.0, 0.0, 0.0] for _ in payload["input"]]}, headers=headers)
        if request.url.path == "/api/chat":
            return httpx.Response(200, json={"model": "qwen2.5:3b-instruct",
                "message": {"role": "assistant", "content": "synthetic safe answer"},
                "done": True}, headers=headers)
        raise AssertionError("unexpected local request")
    return httpx.MockTransport(handler)


def test_factory_and_app_creation_have_no_io(tmp_path, monkeypatch):
    root = tmp_path / "existing"
    root.mkdir()
    runtime = create_runtime(root, _settings())
    monkeypatch.setattr(Path, "read_bytes", lambda *_: (_ for _ in ()).throw(AssertionError("I/O")))
    app = create_production_app(runtime)
    assert runtime._started is False
    assert sorted((route.path, next(iter(route.methods))) for route in app.routes) == [
        ("/health", "GET"), ("/v1/audit-events", "GET"), ("/v1/chat", "POST"),
        ("/v1/evaluation-runs", "POST"), ("/v1/evaluation-runs/{run_id}", "GET"),
        ("/v1/reports/{run_id}", "GET")]


def test_ready_runtime_chat_audits_minimal_evidence_and_shutdown_is_idempotent(tmp_path):
    async def exercise() -> None:
        root = _project(tmp_path)
        settings = _settings()
        _write_index(root, settings)
        calls: list[tuple[str, str, object]] = []
        runtime = create_runtime(root, settings, transport=_transport(calls))
        with pytest.raises(ProductionError):
            await runtime.health()
        await runtime.startup()
        health = await runtime.health()
        assert health.ollama.version == "0.12.1"
        assert health.storage.backend == "sqlite"
        request = ChatRequest(subject_id="guest-01", question="synthetic question",
            mode="baseline", corpus_version="synthetic-v1")
        response = await runtime.chat(request)
        assert response.reply == "synthetic safe answer"
        assert response.outcome.value == "answered"
        assert sum(path == "/api/embed" for _, path, _ in calls) == 1
        assert sum(path == "/api/chat" for _, path, _ in calls) == 1
        page = await runtime.list_audit(AuditEventFilter(limit=200))
        assert len(page.items) == 1
        minimized = page.model_dump_json()
        for forbidden in (request.question, response.reply, "messages", "model_output"):
            assert forbidden not in minimized
        metrics = runtime.render_metrics()
        assert "dataguard_chat_requests_total" in metrics
        await runtime.shutdown()
        await runtime.shutdown()
        with pytest.raises(ProductionError):
            await runtime.health()
    asyncio.run(exercise())


def test_startup_reschedules_persisted_queued_runs_in_fifo_order(tmp_path, monkeypatch):
    class Task:
        def add_done_callback(self, _callback):
            pass

    class Scheduler:
        def __init__(self):
            self.run_ids = []

        def schedule(self, run_id):
            self.run_ids.append(run_id)
            return Task()

        async def shutdown(self):
            pass

    async def exercise() -> None:
        root = _project(tmp_path)
        settings = _settings()
        _write_index(root, settings)
        repository = create_audit_repository(settings, root)
        repository.prepare_schema()
        later = repository.create_run(
            "synthetic-v1", EvaluationProfile.EXPLORATORY,
            production_module.datetime(2026, 8, 11, 1, 0, 1,
                                       tzinfo=production_module.timezone.utc))
        first = repository.create_run(
            "synthetic-v1", EvaluationProfile.EXPLORATORY,
            production_module.datetime(2026, 8, 11, 1, 0, 0,
                                       tzinfo=production_module.timezone.utc))
        repository.close()
        scheduler = Scheduler()
        monkeypatch.setattr(
            production_module, "create_evaluation_scheduler", lambda _runner: scheduler)
        runtime = create_runtime(root, settings, transport=_transport([]))
        await runtime.startup()
        assert scheduler.run_ids == [first.run_id, later.run_id]
        await runtime.shutdown()

    asyncio.run(exercise())


@pytest.mark.parametrize("fault", ["first_schedule", "middle_schedule", "callback"])
def test_queued_recovery_publication_failure_rolls_back_runtime(
    tmp_path, monkeypatch, fault,
):
    class Task:
        def add_done_callback(self, _callback):
            if fault == "callback":
                raise RuntimeError("raw callback failure")

    class Scheduler:
        def __init__(self):
            self.schedule_calls = 0
            self.shutdown_calls = 0

        def schedule(self, _run_id):
            self.schedule_calls += 1
            if fault == "first_schedule" or (
                fault == "middle_schedule" and self.schedule_calls == 2
            ):
                raise RuntimeError("raw schedule failure")
            return Task()

        async def shutdown(self):
            self.shutdown_calls += 1

    async def exercise() -> None:
        root = _project(tmp_path)
        settings = _settings()
        _write_index(root, settings)
        repository = create_audit_repository(settings, root)
        repository.prepare_schema()
        for second in range(2):
            repository.create_run(
                "synthetic-v1", EvaluationProfile.EXPLORATORY,
                production_module.datetime(2026, 8, 11, 1, 0, second,
                                           tzinfo=production_module.timezone.utc))
        repository.close()
        scheduler = Scheduler()
        monkeypatch.setattr(
            production_module, "create_evaluation_scheduler", lambda _runner: scheduler)
        runtime = create_runtime(root, settings, transport=_transport([]))
        with pytest.raises(ProductionError) as captured:
            await runtime.startup()
        assert "raw" not in str(captured.value) + repr(captured.value)
        assert scheduler.shutdown_calls == 1
        assert runtime._started is False
        assert runtime._services_ready is False
        for name in (
            "_repository", "_client", "_scheduler", "_health", "_report_contract",
            "_metrics", "_planner", "_executor", "_context", "_run_metrics",
        ):
            assert getattr(runtime, name) is None

    asyncio.run(exercise())


def test_required_chat_audit_failure_never_returns_model_reply(tmp_path, monkeypatch):
    async def exercise() -> None:
        root = _project(tmp_path)
        settings = _settings()
        _write_index(root, settings)
        calls: list[tuple[str, str, object]] = []
        runtime = create_runtime(root, settings, transport=_transport(calls))
        await runtime.startup()
        repository_type = type(runtime._repository)
        monkeypatch.setattr(repository_type, "append_event",
                            lambda *_: (_ for _ in ()).throw(RuntimeError("raw sentinel")))
        with pytest.raises(ProductionError) as captured:
            await runtime.chat(ChatRequest(subject_id="guest-01", question="synthetic question",
                mode="baseline", corpus_version="synthetic-v1"))
        assert captured.value.code == "storage_unavailable"
        assert "raw sentinel" not in repr(captured.value)
        assert sum(path == "/api/chat" for _, path, _ in calls) == 1
        await runtime.shutdown()
    asyncio.run(exercise())


def test_missing_index_is_cached_not_ready_without_rebuild(tmp_path):
    async def exercise() -> None:
        root = _project(tmp_path)
        calls: list[tuple[str, str, object]] = []
        runtime = create_runtime(root, _settings(), transport=_transport(calls))
        await runtime.startup()
        assert (await runtime.health()).evidence_readiness is False
        with pytest.raises(ProductionError):
            await runtime.chat(ChatRequest(subject_id="guest-01", question="x",
                mode="baseline", corpus_version="synthetic-v1"))
        assert not any(path == "/api/embed" for _, path, _ in calls)
        await runtime.shutdown()
    asyncio.run(exercise())


@pytest.mark.parametrize("state", ["corrupt", "stale"])
def test_invalid_index_states_are_cached_not_ready_without_rebuild(tmp_path, state):
    async def exercise() -> None:
        root = _project(tmp_path)
        settings = _settings()
        if state == "stale":
            _write_index(root, settings, embedding_digest="c" * 64)
        else:
            store = VectorIndexStore(root, settings)
            store.prepare()
            (root / settings.runtime_state_dir / "vector-index.v1.json").write_bytes(b"{}\n")
        calls: list[tuple[str, str, object]] = []
        runtime = create_runtime(root, settings, transport=_transport(calls))
        await runtime.startup()
        assert (await runtime.health()).evidence_readiness is False
        assert not any(path == "/api/embed" for _, path, _ in calls)
        await runtime.shutdown()
    asyncio.run(exercise())


def test_runtime_exposes_cached_ollama_dependency_failure_via_health_and_services(tmp_path):
    async def exercise() -> None:
        root = _project(tmp_path)
        settings = _settings()
        _write_index(root, settings)
        async def fail(_request):
            raise httpx.ConnectError("raw remote sentinel")
        runtime = create_runtime(root, settings, transport=httpx.MockTransport(fail))
        await runtime.startup()
        health = await runtime.health()
        assert health.status.value == "unhealthy"
        assert "ollama_unavailable" in {reason.value for reason in health.reasons}
        with pytest.raises(ProductionError) as captured:
            await runtime.chat(ChatRequest(subject_id="guest-01", question="x",
                mode="baseline", corpus_version="synthetic-v1"))
        assert captured.value.code == "ollama_unavailable"
        assert "raw remote sentinel" not in repr(captured.value)
        await runtime.shutdown()
    asyncio.run(exercise())


def test_runtime_exposes_cached_storage_dependency_failure_via_health_and_services(
        tmp_path, monkeypatch):
    async def exercise() -> None:
        root = _project(tmp_path)
        settings = _settings()
        _write_index(root, settings)
        monkeypatch.setattr(production_module, "create_audit_repository",
            lambda *_: (_ for _ in ()).throw(RuntimeError("raw database sentinel")))
        runtime = create_runtime(root, settings, transport=_transport([]))
        await runtime.startup()
        health = await runtime.health()
        assert health.status.value == "unhealthy"
        assert "storage_unavailable" in {reason.value for reason in health.reasons}
        with pytest.raises(ProductionError) as captured:
            await runtime.chat(ChatRequest(subject_id="guest-01", question="x",
                mode="baseline", corpus_version="synthetic-v1"))
        assert captured.value.code == "storage_unavailable"
        with pytest.raises(ProductionError) as captured:
            await runtime.list_audit(AuditEventFilter(limit=1))
        assert captured.value.code == "storage_unavailable"
        assert "raw database sentinel" not in repr(captured.value)
        await runtime.shutdown()
    asyncio.run(exercise())


def test_evaluation_admission_creates_new_queued_runs_without_dedup(tmp_path, monkeypatch):
    async def exercise() -> None:
        root = _project(tmp_path)
        settings = _settings()
        _write_index(root, settings)
        runtime = create_runtime(root, settings, transport=_transport([]))
        await runtime.startup()
        scheduled: list[str] = []

        class Done:
            def add_done_callback(self, callback):
                return None

        scheduler_type = type(runtime._scheduler)
        def commit(self, reservation, run_id):
            self._reservations.remove(reservation._identity)
            scheduled.append(run_id)
            return Done()
        monkeypatch.setattr(scheduler_type, "commit", commit)
        request = EvaluationRunRequest(scenario_set_version="synthetic-v1",
                                       profile=EvaluationProfile.EXPLORATORY)
        first = await runtime.create_run(request)
        second = await runtime.create_run(request)
        assert first.run_id != second.run_id
        assert scheduled == [first.run_id, second.run_id]
        assert first.status.value == second.status.value == "queued"
        await runtime.shutdown()
    asyncio.run(exercise())


def test_six_production_endpoints_close_full_local_sqlite_background_run(tmp_path, monkeypatch):
    async def exercise() -> None:
        root = _project(tmp_path)
        settings = _settings()
        _write_index(root, settings)
        calls: list[tuple[str, str, object]] = []
        runtime = create_runtime(root, settings, transport=_transport(calls))
        app = create_production_app(runtime)
        async with app.router.lifespan_context(app):
            repository_type = type(runtime._repository)
            original_append = repository_type.append_event
            def fail_terminal_audit(self, event):
                if event.event_type.value == "run_state_changed":
                    raise StorageError()
                return original_append(self, event)
            monkeypatch.setattr(repository_type, "append_event", fail_terminal_audit)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://local.test") as client:
                health = await client.get("/health")
                assert health.status_code == 200
                chat = await client.post("/v1/chat", json={"subject_id": "guest-01",
                    "question": "synthetic question", "mode": "guarded",
                    "corpus_version": "synthetic-v1"})
                assert chat.status_code == 200
                created = await client.post("/v1/evaluation-runs", json={
                    "scenario_set_version": "synthetic-v1", "profile": "exploratory"})
                assert created.status_code == 202
                run_id = created.json()["run_id"]
                tasks = tuple(runtime._scheduler._tasks)
                assert len(tasks) == 1
                completed = await tasks[0]
                assert completed.status.value == "completed"
                run = await client.get(f"/v1/evaluation-runs/{run_id}")
                assert run.status_code == 200
                assert run.json()["completed_scenarios"] == 62
                audit = await client.get("/v1/audit-events?limit=200")
                assert audit.status_code == 200
                events = audit.json()["items"]
                assert sum(item["event_type"] == "output_detection_completed" for item in events) == 124
                assert all("question" not in json.dumps(item) for item in events)
                report = await client.get(f"/v1/reports/{run_id}")
                assert report.status_code == 200
                assert report.json()["run_id"] == run_id
                html = await client.get(f"/v1/reports/{run_id}?format=html")
                assert html.status_code == 200
                assert "<script" not in html.text.lower()
                metrics = runtime.render_metrics()
                for mode in ("baseline", "guarded"):
                    for family in ("direct_prompt_injection", "indirect_document_injection",
                                   "cross_role_retrieval", "system_prompt_inducement"):
                        assert (f'dataguard_attack_attempts_total{{mode="{mode}",'
                            f'attack_family="{family}"}} 8') in metrics
                    qa_lines = [line for line in metrics.splitlines()
                        if line.startswith(f'dataguard_authorized_qa_results_total{{mode="{mode}"')]
                    assert sum(int(line.rsplit(" ", 1)[1]) for line in qa_lines) == 30
                assert ('dataguard_ollama_requests_total{operation="embedding",result="success"} 63'
                        in metrics)
                assert ('dataguard_ollama_requests_total{operation="generation",result="success"} 125'
                        in metrics)
                assert ('dataguard_evaluation_runs_total{profile="exploratory",status="running",'
                        'storage_backend="sqlite"} 1') in metrics
                assert ('dataguard_evaluation_runs_total{profile="exploratory",status="completed",'
                        'storage_backend="sqlite"} 1') in metrics
                assert ('dataguard_evidence_write_failures_total{backend="sqlite",'
                        'record_type="audit_event"} 1') in metrics
                assert runtime._run_metrics._started == {}
        assert sum(path == "/api/embed" for _, path, _ in calls) == 63
        assert sum(path == "/api/chat" for _, path, _ in calls) == 125
    asyncio.run(exercise())


def test_scenario_audit_failure_is_run_fatal_and_persists_no_report(tmp_path, monkeypatch):
    async def exercise() -> None:
        root = _project(tmp_path)
        settings = _settings()
        _write_index(root, settings)
        runtime = create_runtime(root, settings, transport=_transport([]))
        await runtime.startup()
        repository_type = type(runtime._repository)
        original = repository_type.append_event
        def fail_scenario(self, event):
            if event.event_type.value == "output_detection_completed":
                raise StorageError()
            return original(self, event)
        monkeypatch.setattr(repository_type, "append_event", fail_scenario)
        run = await runtime.create_run(EvaluationRunRequest(
            scenario_set_version="synthetic-v1", profile="exploratory"))
        task = tuple(runtime._scheduler._tasks)[0]
        with pytest.raises(Exception):
            await task
        terminal = await runtime.get_run(run.run_id)
        assert terminal.status.value == "failed"
        assert terminal.failure_code.value == "storage_unavailable"
        with pytest.raises(Exception) as captured:
            await runtime.get_report(run.run_id)
        assert getattr(captured.value, "code", None) == "report_unavailable"
        await runtime.shutdown()
    asyncio.run(exercise())


def test_shutdown_closes_remaining_dependencies_when_scheduler_shutdown_fails(tmp_path, monkeypatch):
    async def exercise() -> None:
        root = _project(tmp_path)
        settings = _settings()
        _write_index(root, settings)
        runtime = create_runtime(root, settings, transport=_transport([]))
        await runtime.startup()
        closed = {"client": 0, "repository": 0}
        client_type = type(runtime._client)
        repository_type = type(runtime._repository)
        scheduler_type = type(runtime._scheduler)
        original_client_close = client_type.aclose
        original_repository_close = repository_type.close
        async def close_client(self):
            closed["client"] += 1
            await original_client_close(self)
        def close_repository(self):
            closed["repository"] += 1
            return original_repository_close(self)
        async def fail_shutdown(self):
            raise RuntimeError("raw shutdown sentinel")
        monkeypatch.setattr(client_type, "aclose", close_client)
        monkeypatch.setattr(repository_type, "close", close_repository)
        monkeypatch.setattr(scheduler_type, "shutdown", fail_shutdown)
        with pytest.raises(ProductionError) as captured:
            await runtime.shutdown()
        assert closed == {"client": 1, "repository": 1}
        assert "raw shutdown sentinel" not in repr(captured.value)
        await runtime.shutdown()
    asyncio.run(exercise())
