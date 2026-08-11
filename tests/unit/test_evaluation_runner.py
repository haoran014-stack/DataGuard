from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest

from dataguard.detector import build_whole_output_detector
from dataguard.evaluation import (
    EvaluationRunner, EvaluationRunnerError, EvaluationScheduleError,
    MAX_EVALUATION_CONCURRENCY, MAX_SCHEDULED_TASKS, create_evaluation_runner,
    create_evaluation_scheduler,
)
from dataguard.ollama import OllamaClient
from dataguard.rag import (
    RagPlanningError, RagPlanningErrorCode, create_rag_executor, create_rag_planner,
)
from dataguard.storage import (
    ErrorCode, EvaluationProfile, EvaluationRun, ReportValidationError,
    RunStatus, StorageError,
)
from tests.support.evaluation_factory import build_unit_scenario_evidence


RUN_ID = "00000000-0000-4000-8000-000000008000"
RAW = "RUNNER-RAW-SENTINEL"


class FakeClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 8, 11, 4, tzinfo=timezone.utc)
        self.ticks = 0

    def now(self) -> datetime:
        self.current += timedelta(microseconds=1)
        return self.current

    def monotonic_ns(self) -> int:
        self.ticks += 1_000_000
        return self.ticks


class TraceIds:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"00000000-0000-4000-8000-{self.value:012d}"


class FakeRepository:
    def __init__(self, profile: EvaluationProfile = EvaluationProfile.EVIDENCE,
                 *, complete_error: Exception | None = None,
                 start_profile: EvaluationProfile | None = None,
                 fail_error: Exception | None = None,
                 forged_complete_return: bool = False,
                 advance_error_at: int | None = None) -> None:
        created = datetime(2026, 8, 11, 3, tzinfo=timezone.utc)
        self.run = EvaluationRun(run_id=RUN_ID, status=RunStatus.QUEUED,
            scenario_set_version="synthetic-v1", profile=profile,
            completed_scenarios=0, total_scenarios=62, created_at=created,
            updated_at=created, completed_at=None, failure_code=None)
        self.calls: list[tuple[str, Any]] = []
        self.report: dict[str, Any] | None = None
        self.complete_error = complete_error
        self.start_profile = start_profile
        self.fail_error = fail_error
        self.forged_complete_return = forged_complete_return
        self.advance_error_at = advance_error_at

    def start_run(self, run_id: str, updated_at: datetime) -> EvaluationRun:
        self.calls.append(("start", run_id))
        profile = self.start_profile or self.run.profile
        self.run = self.run.model_copy(update={"status": RunStatus.RUNNING,
            "profile": profile, "updated_at": updated_at})
        return self.run

    def advance_run(self, run_id: str, updated_at: datetime) -> EvaluationRun:
        self.calls.append(("advance", self.run.completed_scenarios + 1))
        if self.advance_error_at == self.run.completed_scenarios + 1:
            raise StorageError()
        self.run = self.run.model_copy(update={
            "completed_scenarios": self.run.completed_scenarios + 1,
            "updated_at": updated_at})
        return self.run

    def fail_run(self, run_id: str, failure_code: ErrorCode,
                 updated_at: datetime) -> EvaluationRun:
        self.calls.append(("fail", failure_code.value))
        if self.fail_error is not None:
            raise self.fail_error
        if self.run.status is not RunStatus.RUNNING:
            raise StorageError()
        self.run = self.run.model_copy(update={"status": RunStatus.FAILED,
            "failure_code": failure_code, "updated_at": updated_at})
        return self.run

    def complete_run(self, run_id: str, report: dict[str, Any],
                     completed_at: datetime) -> EvaluationRun:
        self.calls.append(("complete", run_id))
        if self.complete_error is not None:
            raise self.complete_error
        assert self.run.completed_scenarios == 61
        self.report = report
        self.run = self.run.model_copy(update={"status": RunStatus.COMPLETED,
            "completed_scenarios": 62, "updated_at": completed_at,
            "completed_at": completed_at, "failure_code": None})
        if self.forged_complete_return:
            return self.run.model_copy(update={
                "run_id": "00000000-0000-4000-8000-000000008099"})
        return self.run


@pytest.fixture(scope="module")
def context():
    value, _scenarios = asyncio.run(build_unit_scenario_evidence())
    return value


def _handler(context, counters: Counter[str], *, embed_status: int = 200,
             first_chat_timeout: bool = False, block_embed: asyncio.Event | None = None):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/embed":
            counters["embed"] += 1
            if block_embed is not None:
                await block_embed.wait()
            if embed_status != 200:
                return httpx.Response(embed_status, headers={"Content-Type": "application/json"})
            dimensions = context.health.embedding_dimensions
            return httpx.Response(200, json={"model": "qwen3-embedding:0.6b",
                "embeddings": [[1.0, *([0.0] * (dimensions - 1))]]},
                headers={"Content-Type": "application/json"})
        counters["chat"] += 1
        if first_chat_timeout and counters["chat"] == 1:
            raise httpx.ReadTimeout(RAW)
        return httpx.Response(200, json={"model": "qwen2.5:3b-instruct",
            "message": {"role": "assistant", "content": "unit safe response"},
            "done": True}, headers={"Content-Type": "application/json"})
    return handler


async def _components(context, repository: FakeRepository, counters: Counter[str],
                      **handler_options):
    client = OllamaClient(context.settings,
        transport=httpx.MockTransport(_handler(context, counters, **handler_options)))
    planner = create_rag_planner(context.bundle.identities, context.bundle.corpus,
        context.bundle.corpus_sha256, context.resources,
        context.loaded_index.validated_index)
    executor = create_rag_executor(client,
        build_whole_output_detector(context.resources, context.bundle.corpus))
    runner = create_evaluation_runner(context, planner, executor, repository,
                                      FakeClock(), TraceIds())
    return client, planner, executor, runner


def test_runner_exact_order_counts_progress_and_atomic_completion(context, monkeypatch) -> None:
    async def exercise() -> None:
        counters: Counter[str] = Counter()
        repository = FakeRepository()
        client, planner, executor, runner = await _components(context, repository, counters)
        plan_calls = 0
        execute_modes: list[str] = []
        original_plan = type(planner).plan_pair
        original_execute = type(executor).execute

        async def plan_spy(self, **kwargs):
            nonlocal plan_calls
            plan_calls += 1
            return await original_plan(self, **kwargs)

        async def execute_spy(self, plan):
            execute_modes.append(plan.mode.value)
            return await original_execute(self, plan)

        monkeypatch.setattr(type(planner), "plan_pair", plan_spy)
        monkeypatch.setattr(type(executor), "execute", execute_spy)
        async with client:
            result = await runner.run(RUN_ID)
        assert result.status is RunStatus.COMPLETED
        assert counters == {"embed": 62, "chat": 124}
        assert plan_calls == 62
        assert execute_modes == [mode for _ in range(62) for mode in ("baseline", "guarded")]
        names = [name for name, _ in repository.calls]
        assert names == ["start", *(["advance"] * 61), "complete"]
        assert repository.report is not None
        assert len(repository.report["scenario_results"]) == 62
    asyncio.run(exercise())


def test_shared_embedding_failure_uses_no_plan_or_generation(context, monkeypatch) -> None:
    async def exercise() -> None:
        counters: Counter[str] = Counter()
        repository = FakeRepository()
        client, planner, executor, runner = await _components(
            context, repository, counters, embed_status=404)
        monkeypatch.setattr(type(planner), "plan_pair",
            lambda *args, **kwargs: pytest.fail("planning must not run"))
        monkeypatch.setattr(type(executor), "execute",
            lambda *args, **kwargs: pytest.fail("generation must not run"))
        async with client:
            result = await runner.run(RUN_ID)
        assert result.status is RunStatus.COMPLETED and counters == {"embed": 62}
        assert repository.report is not None
        assert repository.report["summary"]["indeterminate_mode_results"] == 124
        assert all(not item[mode]["attack_delivered"]
            for item in repository.report["scenario_results"]
            for mode in ("baseline", "guarded"))
    asyncio.run(exercise())


def test_single_generation_failure_is_mode_local_and_other_mode_runs(context) -> None:
    async def exercise() -> None:
        counters: Counter[str] = Counter()
        repository = FakeRepository()
        client, _planner, _executor, runner = await _components(
            context, repository, counters, first_chat_timeout=True)
        async with client:
            await runner.run(RUN_ID)
        assert counters == {"embed": 62, "chat": 124}
        assert repository.report is not None
        first = repository.report["scenario_results"][0]
        assert first["baseline"]["error_code"] == "model_timeout"
        assert first["guarded"]["outcome"] == "answered"
        assert repository.report["summary"]["indeterminate_mode_results"] == 1
    asyncio.run(exercise())


@pytest.mark.parametrize("failure", ["context_budget", "complete_validation", "complete_storage"])
def test_fatal_faults_fail_run_without_partial_report(context, monkeypatch, failure: str) -> None:
    async def exercise() -> None:
        counters: Counter[str] = Counter()
        complete_error = (ReportValidationError() if failure == "complete_validation"
            else StorageError() if failure == "complete_storage" else None)
        repository = FakeRepository(complete_error=complete_error)
        client, planner, _executor, runner = await _components(context, repository, counters)
        if failure == "context_budget":
            async def fail_plan(*args, **kwargs):
                raise RagPlanningError(RagPlanningErrorCode.CONTEXT_BUDGET_EXCEEDED)
            monkeypatch.setattr(type(planner), "plan_pair", fail_plan)
        async with client:
            with pytest.raises(EvaluationRunnerError) as error:
                await runner.run(RUN_ID)
        expected = ("context_budget_exceeded" if failure == "context_budget"
            else "experiment_manifest_mismatch" if failure == "complete_validation"
            else "storage_unavailable")
        assert error.value.code == expected
        assert repository.run.status is RunStatus.FAILED
        assert repository.report is None
        assert RAW not in str(error.value) + repr(error.value) + repr(error.value.as_dict())
    asyncio.run(exercise())


def test_run_binding_drift_fails_after_atomic_start(context) -> None:
    async def exercise() -> None:
        counters: Counter[str] = Counter()
        repository = FakeRepository(start_profile=EvaluationProfile.EXPLORATORY)
        client, _planner, _executor, runner = await _components(context, repository, counters)
        async with client:
            with pytest.raises(EvaluationRunnerError) as error:
                await runner.run(RUN_ID)
        assert error.value.code == "experiment_manifest_mismatch"
        assert repository.run.status is RunStatus.FAILED and not counters
    asyncio.run(exercise())


@pytest.mark.parametrize("stage", ["plan_manifest", "executor_internal", "advance_storage"])
def test_early_fatal_matrix_is_content_safe_and_writes_no_report(
    context, monkeypatch, stage: str,
) -> None:
    async def exercise() -> None:
        counters: Counter[str] = Counter()
        repository = FakeRepository(advance_error_at=1 if stage == "advance_storage" else None)
        client, planner, executor, runner = await _components(context, repository, counters)
        if stage == "plan_manifest":
            async def fail_plan(*args, **kwargs):
                raise RagPlanningError(RagPlanningErrorCode.EXPERIMENT_MANIFEST_MISMATCH)
            monkeypatch.setattr(type(planner), "plan_pair", fail_plan)
        elif stage == "executor_internal":
            async def fail_execute(*args, **kwargs):
                raise RuntimeError(RAW)
            monkeypatch.setattr(type(executor), "execute", fail_execute)
        async with client:
            with pytest.raises(EvaluationRunnerError) as error:
                await runner.run(RUN_ID)
        expected = "storage_unavailable" if stage == "advance_storage" \
            else "experiment_manifest_mismatch" if stage == "plan_manifest" else "internal_error"
        assert error.value.code == expected
        assert repository.report is None and repository.run.status is RunStatus.FAILED
        assert RAW not in str(error.value) + repr(error.value) + repr(error.value.as_dict())
    asyncio.run(exercise())


def test_complete_commit_with_forged_return_is_internal_and_not_rollbackable(context) -> None:
    async def exercise() -> None:
        counters: Counter[str] = Counter()
        repository = FakeRepository(forged_complete_return=True)
        client, _planner, _executor, runner = await _components(context, repository, counters)
        async with client:
            with pytest.raises(EvaluationRunnerError) as error:
                await runner.run(RUN_ID)
        assert error.value.code == "internal_error"
        assert repository.run.status is RunStatus.COMPLETED
        assert repository.report is not None
        assert repository.calls[-1] == ("fail", "internal_error")
    asyncio.run(exercise())


def test_cancellation_propagates_and_best_effort_fails_internal(context) -> None:
    async def exercise() -> None:
        counters: Counter[str] = Counter()
        repository = FakeRepository()
        never = asyncio.Event()
        client, _planner, _executor, runner = await _components(
            context, repository, counters, block_embed=never)
        async with client:
            task = asyncio.create_task(runner.run(RUN_ID))
            while counters["embed"] == 0:
                await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert repository.run.status is RunStatus.FAILED
        assert repository.run.failure_code is ErrorCode.INTERNAL_ERROR
    asyncio.run(exercise())


def test_cancellation_still_propagates_when_best_effort_storage_fail_fails(context) -> None:
    async def exercise() -> None:
        counters: Counter[str] = Counter()
        repository = FakeRepository(fail_error=StorageError())
        never = asyncio.Event()
        client, _planner, _executor, runner = await _components(
            context, repository, counters, block_embed=never)
        async with client:
            task = asyncio.create_task(runner.run(RUN_ID))
            while counters["embed"] == 0:
                await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert repository.run.status is RunStatus.RUNNING
        assert repository.calls[-1] == ("fail", "internal_error")
    asyncio.run(exercise())


def test_scheduler_is_bounded_serial_reclaims_tasks_and_does_not_deduplicate(
    context, monkeypatch
) -> None:
    async def exercise() -> None:
        counters: Counter[str] = Counter()
        repository = FakeRepository()
        client, _planner, _executor, runner = await _components(context, repository, counters)
        active = 0
        peak = 0
        release = asyncio.Event()

        async def controlled_run(self, run_id):
            nonlocal active, peak
            active += 1; peak = max(peak, active)
            await release.wait()
            active -= 1
            return repository.run

        monkeypatch.setattr(EvaluationRunner, "run", controlled_run)
        scheduler = create_evaluation_scheduler(runner)
        tasks = [scheduler.schedule(f"run-{index}") for index in range(2)]
        await asyncio.sleep(0)
        assert MAX_EVALUATION_CONCURRENCY == 1 and peak == 1 and scheduler.active_count == 2
        release.set()
        await asyncio.gather(*tasks)
        await asyncio.sleep(0)
        assert scheduler.active_count == 0
        duplicate = [scheduler.schedule("same-run") for _ in range(2)]
        await asyncio.gather(*duplicate)
        await scheduler.shutdown()
        with pytest.raises(EvaluationScheduleError):
            scheduler.schedule("closed")
        assert MAX_SCHEDULED_TASKS == 64
        await client.aclose()
    asyncio.run(exercise())


def test_scheduler_shutdown_cancels_all_tasks(context, monkeypatch) -> None:
    async def exercise() -> None:
        counters: Counter[str] = Counter()
        repository = FakeRepository()
        client, _planner, _executor, runner = await _components(context, repository, counters)
        started = asyncio.Event()

        async def blocked(self, run_id):
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(EvaluationRunner, "run", blocked)
        scheduler = create_evaluation_scheduler(runner)
        scheduler.schedule("one")
        await started.wait()
        await scheduler.shutdown()
        await asyncio.sleep(0)
        assert scheduler.active_count == 0
        await client.aclose()
    asyncio.run(exercise())


def test_scheduler_registry_capacity_is_hard_bounded(context, monkeypatch) -> None:
    async def exercise() -> None:
        counters: Counter[str] = Counter()
        repository = FakeRepository()
        client, _planner, _executor, runner = await _components(context, repository, counters)
        wait = asyncio.Event()

        async def blocked(self, run_id):
            await wait.wait()

        monkeypatch.setattr(EvaluationRunner, "run", blocked)
        scheduler = create_evaluation_scheduler(runner)
        for index in range(MAX_SCHEDULED_TASKS):
            scheduler.schedule(f"queued-{index}")
        with pytest.raises(EvaluationScheduleError):
            scheduler.schedule("overflow")
        assert scheduler.active_count == MAX_SCHEDULED_TASKS
        await scheduler.shutdown()
        await client.aclose()
    asyncio.run(exercise())


def test_scheduler_consumes_background_exception_without_rendering(context, monkeypatch) -> None:
    async def exercise() -> None:
        counters: Counter[str] = Counter()
        repository = FakeRepository()
        client, _planner, _executor, runner = await _components(context, repository, counters)

        async def failed(self, run_id):
            raise EvaluationRunnerError(ErrorCode.INTERNAL_ERROR)

        monkeypatch.setattr(EvaluationRunner, "run", failed)
        scheduler = create_evaluation_scheduler(runner)
        task = scheduler.schedule(RAW)
        while not task.done():
            await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert scheduler.active_count == 0
        assert getattr(task, "_log_traceback", False) is False
        await scheduler.shutdown()
        await client.aclose()
    asyncio.run(exercise())


def test_runner_factory_and_error_are_controlled_and_minimized(context) -> None:
    error = EvaluationRunnerError(ErrorCode.INTERNAL_ERROR)
    for name in ("_code", "args"):
        with pytest.raises(AttributeError):
            setattr(error, name, RAW)
    assert RAW not in str(error) + repr(error) + repr(error.as_dict())
    with pytest.raises(TypeError):
        EvaluationRunner(context, object(), object(), object(), object(), object())  # type: ignore[call-arg]


def test_runner_factory_rejects_executor_client_settings_drift(context) -> None:
    async def exercise() -> None:
        counters: Counter[str] = Counter()
        repository = FakeRepository()
        client, planner, executor, _runner = await _components(context, repository, counters)
        original = client._max_response_bytes
        client._max_response_bytes = original + 1
        try:
            with pytest.raises(EvaluationRunnerError) as error:
                create_evaluation_runner(context, planner, executor, repository,
                                         FakeClock(), TraceIds())
            assert error.value.code == "experiment_manifest_mismatch"
        finally:
            client._max_response_bytes = original
            await client.aclose()
    asyncio.run(exercise())
