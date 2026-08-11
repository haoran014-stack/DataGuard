"""Pure deterministic evaluation and complete-report construction."""

from .core import (
    EvaluationContext, create_evaluation_context, evaluate_scenario_pair,
    evaluate_shared_query_failure,
)
from .models import (
    EvaluationError, EvaluationReport, Judgment, ModeEvidence, ModeOutcome,
    PreventionStage, ScenarioEvidence,
)
from .reporting import build_evaluation_report
from .runner import (
    MAX_EVALUATION_CONCURRENCY, MAX_SCHEDULED_TASKS, EvaluationRunner,
    EvaluationRunnerError, EvaluationScheduleError, EvaluationScheduler,
    ScheduleReservation, create_evaluation_runner, create_evaluation_scheduler,
)

__all__ = [
    "EvaluationContext", "EvaluationError", "EvaluationReport", "Judgment",
    "ModeEvidence", "ModeOutcome", "PreventionStage", "ScenarioEvidence",
    "build_evaluation_report", "create_evaluation_context", "evaluate_scenario_pair",
    "evaluate_shared_query_failure",
    "EvaluationRunner", "EvaluationRunnerError", "EvaluationScheduleError",
    "EvaluationScheduler", "MAX_EVALUATION_CONCURRENCY", "MAX_SCHEDULED_TASKS",
    "ScheduleReservation",
    "create_evaluation_runner", "create_evaluation_scheduler",
]
