"""Side-effect-free dependency-injected FastAPI contract shell."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, TypeVar

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response

from dataguard.storage import AuditEventFilter, AuditEventPage, EvaluationRun, StoredReport
from dataguard.validation import validate_chat_response_semantics, validate_evaluation_run_semantics

from .errors import ERROR_CATALOG, PublicProblem, problem_details
from .models import (
    ChatRequest, ChatResponse, EvaluationRunAccepted, EvaluationRunRequest,
    HealthResponse, HealthStatus, canonical_uuid,
)
from .reports import ReportContract, render_report_html

MAX_REQUEST_BODY_BYTES = 16 * 1024


class ApplicationServices(Protocol):
    async def chat(self, request: ChatRequest) -> ChatResponse | Mapping[str, Any]: ...
    async def create_run(self, request: EvaluationRunRequest) -> EvaluationRun | Mapping[str, Any]: ...
    async def get_run(self, run_id: str) -> EvaluationRun | Mapping[str, Any]: ...
    async def list_audit(self, filters: AuditEventFilter) -> AuditEventPage | Mapping[str, Any]: ...
    async def get_report(self, run_id: str) -> StoredReport: ...
    async def health(self) -> HealthResponse | Mapping[str, Any]: ...


ModelT = TypeVar("ModelT", bound=BaseModel)


def _model(value: Any, model_type: type[ModelT]) -> ModelT:
    try:
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="python")
        return model_type.model_validate(value)
    except Exception:
        raise PublicProblem("internal_error") from None


def _json_model(value: BaseModel, *, status: int = 200, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(value.model_dump(mode="json"), status_code=status, headers=headers)


def _public_exception(error: Exception, allowed: frozenset[str]) -> PublicProblem:
    code = getattr(error, "code", None)
    trace_id = getattr(error, "trace_id", None)
    if isinstance(code, Enum):
        code = code.value
    if type(code) is not str or code not in allowed or code not in ERROR_CATALOG:
        return PublicProblem("internal_error")
    return PublicProblem(code, trace_id if type(trace_id) is str else None)


async def _call(operation: Callable[[], Awaitable[Any]], allowed: frozenset[str]) -> Any:
    try:
        return await operation()
    except Exception as error:
        raise _public_exception(error, allowed) from None


def _unique_json(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate")
        result[key] = value
    return result


def _content_type(request: Request) -> None:
    values = [value for key, value in request.scope.get("headers", []) if key.lower() == b"content-type"]
    if len(values) != 1:
        raise PublicProblem("invalid_request")
    try:
        text = values[0].decode("ascii")
        parts = [part.strip() for part in text.split(";")]
    except (UnicodeError, AttributeError):
        raise PublicProblem("invalid_request") from None
    if parts[0].lower() != "application/json" or len(parts) > 2:
        raise PublicProblem("invalid_request")
    if len(parts) == 2:
        name, separator, value = parts[1].partition("=")
        if not separator or name.strip().lower() != "charset" or value.strip().lower() != "utf-8":
            raise PublicProblem("invalid_request")


async def _body(request: Request, model_type: type[ModelT]) -> ModelT:
    _content_type(request)
    lengths = [value for key, value in request.scope.get("headers", []) if key.lower() == b"content-length"]
    if len(lengths) > 1:
        raise PublicProblem("invalid_request")
    if lengths:
        try:
            length = int(lengths[0].decode("ascii"))
        except (ValueError, UnicodeError):
            raise PublicProblem("invalid_request") from None
        if length < 0 or length > MAX_REQUEST_BODY_BYTES:
            raise PublicProblem("invalid_request")
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > MAX_REQUEST_BODY_BYTES:
            raise PublicProblem("invalid_request")
    try:
        payload = json.loads(bytes(raw).decode("utf-8"), object_pairs_hook=_unique_json)
        if type(payload) is not dict:
            raise ValueError("root")
        return model_type.model_validate(payload)
    except (UnicodeError, ValueError, TypeError, json.JSONDecodeError, ValidationError):
        raise PublicProblem("invalid_request") from None


async def _require_empty_body(request: Request) -> None:
    """Reject every GET body, including a stream hidden behind a zero/missing length."""

    lengths = [value for key, value in request.scope.get("headers", [])
               if key.lower() == b"content-length"]
    if len(lengths) > 1:
        raise PublicProblem("invalid_request")
    if lengths:
        try:
            length = int(lengths[0].decode("ascii"))
        except (ValueError, UnicodeError):
            raise PublicProblem("invalid_request") from None
        if length < 0 or length != 0:
            raise PublicProblem("invalid_request")
    async for chunk in request.stream():
        if chunk:
            raise PublicProblem("invalid_request")


def _query(request: Request, allowed: frozenset[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in request.query_params.multi_items():
        if key not in allowed or key in result:
            raise PublicProblem("invalid_request")
        result[key] = value
    return result


def _date(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("date")
        return parsed
    except (ValueError, TypeError):
        raise PublicProblem("invalid_request") from None


def create_app(services: ApplicationServices, report_contract: ReportContract) -> FastAPI:
    """Create the six-route API shell without touching any external dependency."""

    if services is None or type(report_contract) is not ReportContract:
        raise ValueError("application dependencies are invalid")
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)

    @app.exception_handler(PublicProblem)
    async def public_problem_handler(_request: Request, error: PublicProblem) -> JSONResponse:
        details = problem_details(error)
        return JSONResponse(details.model_dump(mode="json"), status_code=details.status,
                            media_type="application/problem+json")

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(_request: Request, _error: RequestValidationError) -> JSONResponse:
        details = problem_details(PublicProblem("invalid_request"))
        return JSONResponse(details.model_dump(mode="json"), status_code=400,
                            media_type="application/problem+json")

    @app.exception_handler(StarletteHTTPException)
    async def starlette_error_handler(_request: Request, error: StarletteHTTPException) -> Response:
        if error.status_code in {404, 405}:
            return Response(status_code=error.status_code)
        details = problem_details(PublicProblem("internal_error"))
        return JSONResponse(details.model_dump(mode="json"), status_code=500,
                            media_type="application/problem+json")

    @app.exception_handler(Exception)
    async def unexpected_handler(_request: Request, _error: Exception) -> JSONResponse:
        details = problem_details(PublicProblem("internal_error"))
        return JSONResponse(details.model_dump(mode="json"), status_code=500,
                            media_type="application/problem+json")

    @app.post("/v1/chat")
    async def chat_endpoint(request: Request) -> Response:
        dto = await _body(request, ChatRequest)
        raw = await _call(lambda: services.chat(dto), frozenset({
            "subject_not_found", "corpus_not_found", "ollama_unavailable",
            "generation_model_unavailable", "embedding_model_unavailable",
            "storage_unavailable", "model_timeout", "model_protocol_error",
            "context_budget_exceeded", "internal_error"}))
        response = _model(raw, ChatResponse)
        if validate_chat_response_semantics(dto.mode.value, response.model_dump(mode="json")):
            raise PublicProblem("internal_error")
        return _json_model(response)

    @app.post("/v1/evaluation-runs", status_code=202)
    async def create_run_endpoint(request: Request) -> Response:
        dto = await _body(request, EvaluationRunRequest)
        raw = await _call(lambda: services.create_run(dto), frozenset({
            "scenario_set_not_found", "experiment_manifest_mismatch", "ollama_unavailable",
            "generation_model_unavailable", "embedding_model_unavailable",
            "storage_unavailable", "internal_error"}))
        run = _model(raw, EvaluationRun)
        if run.status.value != "queued" or validate_evaluation_run_semantics(run.model_dump(mode="json")):
            raise PublicProblem("internal_error")
        accepted = EvaluationRunAccepted(run_id=run.run_id, status="queued")
        return _json_model(accepted, status=202,
            headers={"Location": f"/v1/evaluation-runs/{run.run_id}"})

    @app.get("/v1/evaluation-runs/{run_id}")
    async def get_run_endpoint(run_id: str, request: Request) -> Response:
        await _require_empty_body(request)
        if _query(request, frozenset()): raise PublicProblem("invalid_request")
        try: safe_id = canonical_uuid(run_id)
        except ValueError: raise PublicProblem("invalid_request") from None
        raw = await _call(lambda: services.get_run(safe_id),
                          frozenset({"run_not_found", "storage_unavailable", "internal_error"}))
        run = _model(raw, EvaluationRun)
        if validate_evaluation_run_semantics(run.model_dump(mode="json")):
            raise PublicProblem("internal_error")
        return _json_model(run)

    @app.get("/v1/audit-events")
    async def audit_endpoint(request: Request) -> Response:
        await _require_empty_body(request)
        values = _query(request, frozenset({"trace_id", "run_id", "subject_id", "mode",
            "event_type", "start_time", "end_time", "cursor", "limit"}))
        try:
            for key in ("trace_id", "run_id"):
                if key in values: values[key] = canonical_uuid(values[key])
            for key in ("start_time", "end_time"):
                if key in values: values[key] = _date(values[key])
            if "limit" in values:
                if not values["limit"].isdigit(): raise ValueError("limit")
                values["limit"] = int(values["limit"])
            filters = AuditEventFilter.model_validate(values)
        except PublicProblem: raise
        except Exception: raise PublicProblem("invalid_request") from None
        raw = await _call(lambda: services.list_audit(filters),
                          frozenset({"invalid_request", "storage_unavailable", "internal_error"}))
        page = _model(raw, AuditEventPage)
        return _json_model(page)

    @app.get("/v1/reports/{run_id}")
    async def report_endpoint(run_id: str, request: Request) -> Response:
        await _require_empty_body(request)
        values = _query(request, frozenset({"format"}))
        format_name = values.get("format", "json")
        if format_name not in {"json", "html"}: raise PublicProblem("invalid_request")
        try: safe_id = canonical_uuid(run_id)
        except ValueError: raise PublicProblem("invalid_request") from None
        stored = await _call(lambda: services.get_report(safe_id), frozenset({
            "run_not_found", "report_not_ready", "report_unavailable",
            "storage_unavailable", "internal_error"}))
        try:
            validated = report_contract.validate(stored)
            if validated.as_mapping()["run_id"] != safe_id:
                raise ValueError("report run binding")
            if format_name == "html":
                return Response(render_report_html(validated), media_type="text/html")
            return Response(validated.json_bytes(), media_type="application/json")
        except Exception:
            raise PublicProblem("internal_error") from None

    @app.get("/health")
    async def health_endpoint(request: Request) -> Response:
        await _require_empty_body(request)
        if _query(request, frozenset()): raise PublicProblem("invalid_request")
        raw = await _call(lambda: services.health(), frozenset({"internal_error"}))
        health = _model(raw, HealthResponse)
        return _json_model(health, status=503 if health.status is HealthStatus.UNHEALTHY else 200)

    return app
