"""Controlled 62-pair evaluation runner and bounded in-process scheduler."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from dataguard.detector import build_whole_output_detector
from dataguard.evaluation.core import (
    EvaluationContext, _assert_context_integrity, evaluate_scenario_pair,
    evaluate_shared_query_failure,
)
from dataguard.evaluation.models import EvaluationError, ScenarioEvidence
from dataguard.evaluation.reporting import build_evaluation_report
from dataguard.ollama import OllamaAdapterError, OllamaClient
from dataguard.rag import RagExecutor, RagPlanner, RagPlanningError, embed_query
from dataguard.storage import (
    ErrorCode, EvaluationRun, ReportValidationError, RunStateError, RunStatus,
    StorageError,
)


PAIR_COUNT = 62
PROGRESS_CALLS = 61
MAX_EVALUATION_CONCURRENCY = 1
MAX_SCHEDULED_TASKS = 64
_RUNNER_TOKEN = object()
_SCHEDULER_TOKEN = object()
_GENERATION_FAILURE_CODES = frozenset({
    "ollama_unavailable", "generation_model_unavailable", "model_timeout",
    "model_protocol_error",
})
_SHARED_FAILURE_CODES = frozenset({
    "ollama_unavailable", "embedding_model_unavailable", "model_timeout",
    "model_protocol_error",
})


class RunRepository(Protocol):
    def start_run(self, run_id: str, updated_at: datetime) -> EvaluationRun: ...
    def advance_run(self, run_id: str, updated_at: datetime) -> EvaluationRun: ...
    def fail_run(self, run_id: str, failure_code: ErrorCode,
                 updated_at: datetime) -> EvaluationRun: ...
    def complete_run(self, run_id: str, report: Mapping[str, object],
                     completed_at: datetime) -> EvaluationRun: ...


class RunnerClock(Protocol):
    def now(self) -> datetime: ...
    def monotonic_ns(self) -> int: ...


class EvaluationRunnerError(Exception):
    """Fixed content-free fatal run failure."""

    __slots__ = ("_code",)

    def __init__(self, code: ErrorCode) -> None:
        if type(code) is not ErrorCode:
            code = ErrorCode.INTERNAL_ERROR
        object.__setattr__(self, "_code", code)
        super().__init__("DataGuard could not complete the evaluation run.")

    @property
    def code(self) -> str:
        return self._code.value

    def __repr__(self) -> str:
        return f"EvaluationRunnerError(code={self._code.value!r})"

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}

    def __setattr__(self, name: str, value: object) -> None:
        if name in {"__traceback__", "__cause__", "__context__", "__suppress_context__"}:
            return super().__setattr__(name, value)
        raise AttributeError("evaluation runner errors are fixed")


class EvaluationScheduleError(Exception):
    __slots__ = ()

    def __init__(self) -> None:
        super().__init__("The bounded evaluation scheduler cannot accept the run.")

    def __repr__(self) -> str:
        return "EvaluationScheduleError()"


def _now(clock: RunnerClock) -> datetime:
    try:
        value = clock.now()
        if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError
        return value.astimezone(timezone.utc)
    except Exception:
        raise EvaluationRunnerError(ErrorCode.INTERNAL_ERROR) from None


def _trace(provider: Callable[[], str]) -> str:
    try:
        value = provider()
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError
        return value
    except Exception:
        raise EvaluationRunnerError(ErrorCode.INTERNAL_ERROR) from None


def _latency(clock: RunnerClock, started: int) -> int:
    try:
        ended = clock.monotonic_ns()
        if type(started) is not int or type(ended) is not int or ended < started:
            raise ValueError
        return (ended - started) // 1_000_000
    except Exception:
        raise EvaluationRunnerError(ErrorCode.INTERNAL_ERROR) from None


def _fatal_code(error: Exception) -> ErrorCode:
    if isinstance(error, OllamaAdapterError):
        return ErrorCode(error.code.value)
    if isinstance(error, RagPlanningError):
        return ErrorCode(error.code.value)
    if isinstance(error, ReportValidationError):
        return ErrorCode.EXPERIMENT_MANIFEST_MISMATCH
    if isinstance(error, StorageError):
        return ErrorCode.STORAGE_UNAVAILABLE
    if isinstance(error, EvaluationRunnerError):
        return ErrorCode(error.code)
    if isinstance(error, EvaluationError):
        return ErrorCode.EXPERIMENT_MANIFEST_MISMATCH
    return ErrorCode.INTERNAL_ERROR


@dataclass(frozen=True, slots=True, repr=False, init=False)
class EvaluationRunner:
    _context: EvaluationContext
    _planner: RagPlanner
    _executor: RagExecutor
    _repository: RunRepository
    _clock: RunnerClock
    _trace_id: Callable[[], str]

    def __init__(self, context: EvaluationContext, planner: RagPlanner,
                 executor: RagExecutor, repository: RunRepository,
                 clock: RunnerClock, trace_id_provider: Callable[[], str],
                 *, _token: object) -> None:
        if _token is not _RUNNER_TOKEN:
            raise EvaluationRunnerError(ErrorCode.INTERNAL_ERROR)
        object.__setattr__(self, "_context", context)
        object.__setattr__(self, "_planner", planner)
        object.__setattr__(self, "_executor", executor)
        object.__setattr__(self, "_repository", repository)
        object.__setattr__(self, "_clock", clock)
        object.__setattr__(self, "_trace_id", trace_id_provider)

    def __repr__(self) -> str:
        return "EvaluationRunner(scenarios=62, paired=True)"

    def _validate_started(self, run: object, run_id: str) -> EvaluationRun:
        try:
            safe = EvaluationRun.model_validate(run.model_dump(mode="python"))
            if (safe.run_id != run_id or safe.status is not RunStatus.RUNNING
                    or safe.completed_scenarios != 0 or safe.total_scenarios != PAIR_COUNT
                    or safe.scenario_set_version
                        != self._context.bundle.scenarios.scenario_set_version
                    or safe.profile.value != self._context.settings.profile.value):
                raise ValueError
            return safe
        except Exception:
            raise EvaluationRunnerError(ErrorCode.EXPERIMENT_MANIFEST_MISMATCH) from None

    def _fail_best_effort(self, run_id: str, code: ErrorCode) -> None:
        try:
            self._repository.fail_run(run_id, code, _now(self._clock))
        except Exception:
            pass

    async def run(self, run_id: str) -> EvaluationRun:
        """Execute one existing queued run, producing no partial report."""

        started = False
        try:
            _assert_context_integrity(self._context)
            run = self._repository.start_run(run_id, _now(self._clock))
            started = True
            self._validate_started(run, run_id)
            evidence: list[ScenarioEvidence] = []
            for index, scenario in enumerate(self._context.bundle.scenarios.scenarios):
                baseline_trace = _trace(self._trace_id)
                guarded_trace = _trace(self._trace_id)
                pair_started = self._clock.monotonic_ns()
                try:
                    query = await embed_query(
                        scenario.question, self._context.health, self._executor._client
                    )
                except OllamaAdapterError as error:
                    if error.code.value not in _SHARED_FAILURE_CODES:
                        raise
                    item = evaluate_shared_query_failure(
                        self._context, index, error.code.value,
                        baseline_trace_id=baseline_trace,
                        guarded_trace_id=guarded_trace,
                        latency_ms=_latency(self._clock, pair_started),
                    )
                else:
                    pair = await self._planner.plan_pair(
                        corpus_version=scenario.corpus_version,
                        subject_id=scenario.subject_id,
                        question=scenario.question,
                        query_embedding=query,
                    )
                    mode_results: list[object | None] = []
                    failures: list[str | None] = []
                    latencies: list[int] = []
                    for plan in (pair.baseline, pair.guarded):
                        mode_started = self._clock.monotonic_ns()
                        try:
                            result = await self._executor.execute(plan)
                        except OllamaAdapterError as error:
                            if error.code.value not in _GENERATION_FAILURE_CODES:
                                raise
                            result = None
                            failure = error.code.value
                        else:
                            failure = None
                        mode_results.append(result)
                        failures.append(failure)
                        latencies.append(_latency(self._clock, mode_started))
                    item = evaluate_scenario_pair(
                        self._context, index, pair,
                        mode_results[0], mode_results[1],
                        baseline_trace_id=baseline_trace,
                        guarded_trace_id=guarded_trace,
                        baseline_latency_ms=latencies[0], guarded_latency_ms=latencies[1],
                        baseline_failure_code=failures[0], guarded_failure_code=failures[1],
                    )
                evidence.append(item)
                if index < PROGRESS_CALLS:
                    progressed = self._repository.advance_run(run_id, _now(self._clock))
                    if (type(progressed) is not EvaluationRun
                            or progressed.status is not RunStatus.RUNNING
                            or progressed.completed_scenarios != index + 1):
                        raise EvaluationRunnerError(ErrorCode.INTERNAL_ERROR)

            completed_at = _now(self._clock)
            report = build_evaluation_report(
                self._context, tuple(evidence), report_id=_trace(self._trace_id),
                run_id=run_id, generated_at=completed_at,
            )
            completed = self._repository.complete_run(
                run_id, report.as_mapping(), completed_at
            )
            try:
                safe_completed = EvaluationRun.model_validate(
                    completed.model_dump(mode="python")
                )
                if (safe_completed.run_id != run_id
                        or safe_completed.status is not RunStatus.COMPLETED
                        or safe_completed.completed_scenarios != PAIR_COUNT):
                    raise ValueError
            except Exception:
                raise EvaluationRunnerError(ErrorCode.INTERNAL_ERROR) from None
            return safe_completed
        except asyncio.CancelledError:
            if started:
                self._fail_best_effort(run_id, ErrorCode.INTERNAL_ERROR)
            raise
        except Exception as error:
            code = _fatal_code(error)
            if started:
                self._fail_best_effort(run_id, code)
            raise EvaluationRunnerError(code) from None


def create_evaluation_runner(
    context: EvaluationContext,
    planner: RagPlanner,
    executor: RagExecutor,
    repository: RunRepository,
    clock: RunnerClock,
    trace_id_provider: Callable[[], str],
) -> EvaluationRunner:
    """Bind one context and its exact planner/executor without performing I/O."""

    try:
        context = _assert_context_integrity(context)
        if type(planner) is not RagPlanner or type(executor) is not RagExecutor:
            raise ValueError
        if (planner._index is not context.loaded_index.validated_index
                or planner._binding_facts() != context._expected_pair_facts):
            raise ValueError
        expected_detector = build_whole_output_detector(
            context.resources, context.bundle.corpus
        )
        if (executor._detector._rules != expected_detector._rules
                or executor._detector._fixed_reply != expected_detector._fixed_reply
                or type(executor._client) is not OllamaClient):
            raise ValueError
        client = executor._client
        expected_base = context.settings.ollama_base_url.rstrip("/")
        timeout = client._client.timeout
        if (str(client._client.base_url).rstrip("/") != expected_base
                or client._max_response_bytes != context.settings.ollama_max_response_bytes
                or timeout.connect != context.settings.ollama_connect_timeout_seconds
                or timeout.read != context.settings.ollama_read_timeout_seconds
                or timeout.write != context.settings.ollama_read_timeout_seconds
                or timeout.pool != context.settings.ollama_connect_timeout_seconds
                or client._client.follow_redirects is not False):
            raise ValueError
        for name in ("start_run", "advance_run", "fail_run", "complete_run"):
            if not callable(getattr(repository, name, None)):
                raise ValueError
        if not callable(getattr(clock, "now", None)) \
                or not callable(getattr(clock, "monotonic_ns", None)) \
                or not callable(trace_id_provider):
            raise ValueError
    except Exception:
        raise EvaluationRunnerError(ErrorCode.EXPERIMENT_MANIFEST_MISMATCH) from None
    return EvaluationRunner(context, planner, executor, repository, clock,
                            trace_id_provider, _token=_RUNNER_TOKEN)


@dataclass(frozen=True, slots=True, repr=False, init=False)
class EvaluationScheduler:
    _runner: EvaluationRunner
    _semaphore: asyncio.Semaphore
    _tasks: set[asyncio.Task[EvaluationRun]]
    _closed: bool

    def __init__(self, runner: EvaluationRunner, *, _token: object) -> None:
        if _token is not _SCHEDULER_TOKEN or type(runner) is not EvaluationRunner:
            raise EvaluationScheduleError()
        object.__setattr__(self, "_runner", runner)
        object.__setattr__(self, "_semaphore", asyncio.Semaphore(MAX_EVALUATION_CONCURRENCY))
        object.__setattr__(self, "_tasks", set())
        object.__setattr__(self, "_closed", False)

    def __repr__(self) -> str:
        return ("EvaluationScheduler(max_concurrency=1, "
                f"active={len(self._tasks)}, closed={self._closed})")

    @property
    def active_count(self) -> int:
        return len(self._tasks)

    async def _execute(self, run_id: str) -> EvaluationRun:
        async with self._semaphore:
            return await self._runner.run(run_id)

    def schedule(self, run_id: str) -> asyncio.Task[EvaluationRun]:
        if self._closed or len(self._tasks) >= MAX_SCHEDULED_TASKS:
            raise EvaluationScheduleError()
        task = asyncio.create_task(self._execute(run_id))
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task[EvaluationRun]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        try:
            task.exception()
        except (asyncio.CancelledError, Exception):
            pass

    async def shutdown(self) -> None:
        object.__setattr__(self, "_closed", True)
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def create_evaluation_scheduler(runner: EvaluationRunner) -> EvaluationScheduler:
    return EvaluationScheduler(runner, _token=_SCHEDULER_TOKEN)
