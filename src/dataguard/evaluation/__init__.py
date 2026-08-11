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

__all__ = [
    "EvaluationContext", "EvaluationError", "EvaluationReport", "Judgment",
    "ModeEvidence", "ModeOutcome", "PreventionStage", "ScenarioEvidence",
    "build_evaluation_report", "create_evaluation_context", "evaluate_scenario_pair",
    "evaluate_shared_query_failure",
]
