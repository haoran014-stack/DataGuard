"""Bounded, local-only Ollama adapter.

Importing this package performs no network or filesystem I/O.
"""

from dataguard.ollama.client import OllamaClient
from dataguard.ollama.errors import OllamaAdapterError, OllamaErrorCode
from dataguard.ollama.models import OllamaHealthFacts, OllamaMessage, OllamaModelFacts

__all__ = [
    "OllamaAdapterError",
    "OllamaClient",
    "OllamaErrorCode",
    "OllamaHealthFacts",
    "OllamaMessage",
    "OllamaModelFacts",
]
