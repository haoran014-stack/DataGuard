"""Stage 2 deterministic RAG planning without generation or persistence."""

from dataguard.rag.errors import RagPlanningError, RagPlanningErrorCode
from dataguard.rag.models import AuthorizationDenial, RagMode, RagPlan
from dataguard.rag.planner import (
    QueryEmbedding,
    RagPlanner,
    canonical_documents_json,
    context_message_bytes,
    create_rag_planner,
    embed_query,
)

__all__ = [
    "AuthorizationDenial",
    "QueryEmbedding",
    "RagMode",
    "RagPlan",
    "RagPlanner",
    "RagPlanningError",
    "RagPlanningErrorCode",
    "canonical_documents_json",
    "context_message_bytes",
    "create_rag_planner",
    "embed_query",
]
