"""Stage 2 deterministic RAG planning and guarded local execution."""

from dataguard.rag.errors import RagPlanningError, RagPlanningErrorCode
from dataguard.rag.execution import (
    RagExecutionError,
    RagExecutionErrorCode,
    RagExecutionResult,
    RagExecutor,
    create_rag_executor,
)
from dataguard.rag.models import (
    AuthorizationDenial, PlannerBindingFacts, RequestBindingFacts, RagMode, RagPlan,
)
from dataguard.rag.planner import (
    PairedRagPlans,
    QueryEmbedding,
    RagPlanner,
    canonical_documents_json,
    context_message_bytes,
    create_rag_planner,
    embed_query,
)

__all__ = [
    "AuthorizationDenial",
    "PairedRagPlans",
    "PlannerBindingFacts",
    "RequestBindingFacts",
    "QueryEmbedding",
    "RagExecutionError",
    "RagExecutionErrorCode",
    "RagExecutionResult",
    "RagExecutor",
    "RagMode",
    "RagPlan",
    "RagPlanner",
    "RagPlanningError",
    "RagPlanningErrorCode",
    "canonical_documents_json",
    "context_message_bytes",
    "create_rag_executor",
    "create_rag_planner",
    "embed_query",
]
