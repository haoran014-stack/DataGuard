"""Closed immutable values exchanged with the Ollama adapter."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _ClosedFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        hide_input_in_errors=True,
        allow_inf_nan=False,
    )


class OllamaMessage(_ClosedFrozenModel):
    role: Literal["system", "user"]
    content: str = Field(strict=True, min_length=1, max_length=32_768)

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Ollama message content must not be blank")
        return value


class OllamaModelFacts(_ClosedFrozenModel):
    tag: str = Field(strict=True, min_length=1, max_length=64)
    digest: str = Field(
        strict=True,
        min_length=64,
        max_length=71,
        pattern=r"^(sha256:)?[a-f0-9]{64}$",
    )


class OllamaHealthFacts(_ClosedFrozenModel):
    version: str = Field(strict=True, min_length=1, max_length=64)
    generation_model: OllamaModelFacts
    embedding_model: OllamaModelFacts
    embedding_dimensions: int = Field(strict=True, gt=0)

    @model_validator(mode="after")
    def require_locked_model_tags(self) -> "OllamaHealthFacts":
        if (
            self.generation_model.tag != "qwen2.5:3b-instruct"
            or self.embedding_model.tag != "qwen3-embedding:0.6b"
        ):
            raise ValueError("Ollama health model tags do not match the locked models")
        return self
