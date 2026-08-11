from __future__ import annotations

import asyncio
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from dataguard.api import ReportContract, create_app
from dataguard.api.errors import ERROR_CATALOG, PublicProblem
from dataguard.api.models import ChatResponse, HealthResponse
from dataguard.ollama import OllamaAdapterError, OllamaErrorCode
from dataguard.rag.errors import RagPlanningError, RagPlanningErrorCode
from dataguard.resources import load_security_resources
from dataguard.storage import AuditEventFilter, AuditEventPage, EvaluationRun, StoredReport
from tests.support.report_factory import build_valid_report

PROJECT_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 11, 2, 0, tzinfo=timezone.utc)
RUN_ID = "00000000-0000-4000-8000-000000000901"
TRACE_ID = "00000000-0000-4000-8000-000000000001"
RAW = "RAW-HTTP-SENTINEL"


def _stored_report(*, injection: str | None = None) -> StoredReport:
    report = build_valid_report()
    report["run_id"] = RUN_ID
    report["profile"] = "exploratory"
    report["portfolio_eligible"] = False
    report["experiment"]["storage_backend"] = "sqlite"
    report["generated_at"] = "2026-08-11T02:00:00Z"
    if injection is not None:
        report["experiment"]["ollama_version"] = injection
    raw = json.dumps(report, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    return StoredReport(run_id=RUN_ID, report_id=report["report_id"], generated_at=NOW,
                        sha256=hashlib.sha256(raw).hexdigest(), canonical_json=raw)


def _queued() -> EvaluationRun:
    return EvaluationRun(run_id=RUN_ID, status="queued", scenario_set_version="synthetic-v1",
                         profile="exploratory", completed_scenarios=0, total_scenarios=62,
                         created_at=NOW, updated_at=NOW)


def _health(status: str = "healthy") -> HealthResponse:
    up = status != "unhealthy"
    return HealthResponse(
        status=status, api_version="v1",
        ollama={"status": "up" if up else "down", "version": "1.0",
                "generation_model": {"tag": "qwen2.5:3b-instruct", "digest": "a" * 64,
                                     "available": up},
                "embedding_model": {"tag": "qwen3-embedding:0.6b", "digest": "b" * 64,
                                    "available": up}},
        storage={"status": "up", "backend": "sqlite"},
        evidence_readiness=status == "healthy",
        reasons=[] if status == "healthy" else (["storage_not_postgresql"] if status == "degraded"
                                                  else ["ollama_unavailable"]),
        checked_at=NOW,
    )


class ServiceError(Exception):
    def __init__(self, code: str, *, trace_id: str | None = None) -> None:
        self.code = code
        self.trace_id = trace_id
        super().__init__(RAW)


class FakeServices:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.chat_value: object = ChatResponse(reply="", trace_id=TRACE_ID, outcome="answered")
        self.run_value: object = _queued()
        self.audit_value: object = AuditEventPage(items=(), next_cursor=None)
        self.report_value: object = _stored_report()
        self.health_value: object = _health()

    async def chat(self, request):
        self.calls.append(("chat", request)); return self.chat_value

    async def create_run(self, request):
        self.calls.append(("create_run", request)); return self.run_value

    async def get_run(self, run_id):
        self.calls.append(("get_run", run_id)); return self.run_value

    async def list_audit(self, filters):
        self.calls.append(("list_audit", filters)); return self.audit_value

    async def get_report(self, run_id):
        self.calls.append(("get_report", run_id)); return self.report_value

    async def health(self):
        self.calls.append(("health", None)); return self.health_value


def _app(service: FakeServices):
    schema = json.loads((PROJECT_ROOT / "docs/contracts/report.schema.json").read_text("utf-8"))
    return create_app(service, ReportContract(schema))


async def _request(service: FakeServices, method: str, url: str, **kwargs):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(service),
                                                               raise_app_exceptions=False),
                                 base_url="http://test") as client:
        return await client.request(method, url, **kwargs)


def request(service: FakeServices, method: str, url: str, **kwargs):
    return asyncio.run(_request(service, method, url, **kwargs))


async def _raw_get(service: FakeServices, path: str,
                   headers: list[tuple[bytes, bytes]], body: bytes) -> tuple[int, dict[str, str], bytes]:
    app = _app(service)
    sent: list[dict] = []
    delivered = False

    async def receive() -> dict:
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        sent.append(message)

    await app({"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
               "method": "GET", "scheme": "http", "path": path,
               "raw_path": path.encode("ascii"), "query_string": b"", "headers": headers,
               "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 80),
               "root_path": ""}, receive, send)
    start = next(message for message in sent if message["type"] == "http.response.start")
    content = b"".join(message.get("body", b"") for message in sent
                       if message["type"] == "http.response.body")
    response_headers = {key.decode("ascii"): value.decode("ascii") for key, value in start["headers"]}
    return start["status"], response_headers, content


def _assert_problem(response: httpx.Response, code: str) -> None:
    definition = ERROR_CATALOG[code]
    assert response.status_code == definition.status
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json() == {
        "type": f"https://dataguard.local/problems/{code}", "title": definition.title,
        "status": definition.status, "detail": definition.detail, "code": code,
        "trace_id": response.json()["trace_id"], "retryable": definition.retryable,
    }
    assert str(uuid4()).split("-")[0] != response.json()["trace_id"]


def test_route_inventory_and_disabled_documentation_routes() -> None:
    app = _app(FakeServices())
    routes = {(next(iter(route.methods)), route.path) for route in app.routes}
    assert routes == {("POST", "/v1/chat"), ("POST", "/v1/evaluation-runs"),
                      ("GET", "/v1/evaluation-runs/{run_id}"), ("GET", "/v1/audit-events"),
                      ("GET", "/v1/reports/{run_id}"), ("GET", "/health")}
    for path in ("/docs", "/redoc", "/openapi.json", "/metrics", "/unknown"):
        response = request(FakeServices(), "GET", path)
        assert response.status_code == 404 and response.content == b""


@pytest.mark.parametrize("path", [
    f"/v1/evaluation-runs/{RUN_ID}", "/v1/audit-events",
    f"/v1/reports/{RUN_ID}", "/health",
])
def test_every_get_rejects_body_before_service(path: str) -> None:
    service = FakeServices()
    response = request(service, "GET", path, content=RAW.encode("utf-8"))
    _assert_problem(response, "invalid_request")
    assert service.calls == [] and RAW not in response.text


@pytest.mark.parametrize("path", [
    f"/v1/evaluation-runs/{RUN_ID}", "/v1/audit-events",
    f"/v1/reports/{RUN_ID}", "/health",
])
@pytest.mark.parametrize("headers", [
    [],
    [(b"content-length", b"0")],
    [(b"content-length", b"0"), (b"content-length", b"0")],
    [(b"content-length", b"invalid")],
    [(b"content-length", b"-1")],
])
def test_get_raw_stream_and_content_length_boundaries(path: str,
                                                       headers: list[tuple[bytes, bytes]]) -> None:
    service = FakeServices()
    body = RAW.encode("utf-8") if len(headers) <= 1 and headers not in (
        [(b"content-length", b"invalid")], [(b"content-length", b"-1")]) else b""
    status, response_headers, content = asyncio.run(_raw_get(service, path, headers, body))
    assert status == 400
    assert response_headers["content-type"] == "application/problem+json"
    assert json.loads(content)["code"] == "invalid_request"
    assert service.calls == [] and RAW.encode("utf-8") not in content


@pytest.mark.parametrize("path", [
    f"/v1/evaluation-runs/{RUN_ID}", "/v1/audit-events",
    f"/v1/reports/{RUN_ID}", "/health",
])
def test_get_empty_body_allows_content_type_or_no_content_type(path: str) -> None:
    for headers in ([], [(b"content-type", b"text/plain")]):
        service = FakeServices()
        status, _response_headers, _content = asyncio.run(_raw_get(service, path, headers, b""))
        assert status == 200 and len(service.calls) == 1


def test_chat_success_empty_reply_and_fixed_blocked_reply() -> None:
    service = FakeServices()
    response = request(service, "POST", "/v1/chat",
        json={"subject_id": "guest-01", "question": "   ", "mode": "baseline",
              "corpus_version": "synthetic-v1"})
    assert response.status_code == 200
    assert response.json() == {"reply": "", "trace_id": TRACE_ID, "outcome": "answered"}
    assert service.calls[0][1].question == "   "

    reply = load_security_resources().guard_policy.value.guarded_fixed_reply
    service = FakeServices()
    service.chat_value = {"reply": reply, "trace_id": TRACE_ID, "outcome": "blocked"}
    response = request(service, "POST", "/v1/chat",
        json={"subject_id": "guest-01", "question": "q", "mode": "guarded",
              "corpus_version": "synthetic-v1"})
    assert response.status_code == 200 and response.json()["reply"] == reply


@pytest.mark.parametrize("headers,content", [
    ({}, b"{}"),
    ({"content-type": "text/plain"}, b"{}"),
    ({"content-type": "application/json; charset=latin1"}, b"{}"),
    ({"content-type": "application/json; charset=utf-8; x=y"}, b"{}"),
    ({"content-type": "application/json"}, b"\xff"),
    ({"content-type": "application/json"}, b'{"subject_id":"a","subject_id":"b"}'),
])
def test_chat_rejects_media_utf8_and_duplicate_key(headers, content) -> None:
    response = request(FakeServices(), "POST", "/v1/chat", headers=headers, content=content)
    _assert_problem(response, "invalid_request")
    assert RAW not in response.text


def test_chat_rejects_duplicate_content_type_oversize_unknown_and_semantic_drift() -> None:
    service = FakeServices()
    duplicate = [(b"content-type", b"application/json"), (b"content-type", b"application/json")]
    response = request(service, "POST", "/v1/chat", headers=duplicate, content=b"{}")
    _assert_problem(response, "invalid_request")
    body = {"subject_id": "guest-01", "question": "q", "mode": "baseline",
            "corpus_version": "synthetic-v1", "extra": RAW}
    _assert_problem(request(service, "POST", "/v1/chat", json=body), "invalid_request")
    _assert_problem(request(service, "POST", "/v1/chat",
        headers={"content-type": "application/json"}, content=b" " * 16385), "invalid_request")
    service.chat_value = {"reply": "wrong", "trace_id": TRACE_ID, "outcome": "blocked"}
    response = request(service, "POST", "/v1/chat",
        json={"subject_id": "guest-01", "question": "q", "mode": "guarded",
              "corpus_version": "synthetic-v1"})
    _assert_problem(response, "internal_error")


def test_create_and_get_run_exact_contract_and_errors() -> None:
    service = FakeServices()
    response = request(service, "POST", "/v1/evaluation-runs",
                       json={"scenario_set_version": "synthetic-v1", "profile": "exploratory"})
    assert response.status_code == 202 and response.headers["location"].endswith(RUN_ID)
    assert response.json() == {"run_id": RUN_ID, "status": "queued"}
    assert [name for name, _ in service.calls] == ["create_run"]
    response = request(service, "GET", f"/v1/evaluation-runs/{RUN_ID}")
    assert response.status_code == 200 and response.json()["status"] == "queued"
    _assert_problem(request(service, "GET", "/v1/evaluation-runs/not-a-uuid"), "invalid_request")
    _assert_problem(request(service, "GET", f"/v1/evaluation-runs/{RUN_ID}?extra={RAW}"),
                    "invalid_request")
    service.run_value = {**_queued().model_dump(mode="python"), "completed_scenarios": 1}
    _assert_problem(request(service, "GET", f"/v1/evaluation-runs/{RUN_ID}"), "internal_error")


@pytest.mark.parametrize("status,progress,completed_at,failure_code", [
    ("queued", 0, None, None),
    ("running", 1, None, None),
    ("completed", 62, NOW, None),
    ("failed", 7, None, "model_timeout"),
    ("interrupted", 7, None, "internal_error"),
])
def test_get_run_all_five_states(status, progress, completed_at, failure_code) -> None:
    service = FakeServices()
    service.run_value = EvaluationRun(
        run_id=RUN_ID, status=status, scenario_set_version="synthetic-v1",
        profile="exploratory", completed_scenarios=progress, total_scenarios=62,
        created_at=NOW, updated_at=NOW, completed_at=completed_at,
        failure_code=failure_code)
    response = request(service, "GET", f"/v1/evaluation-runs/{RUN_ID}")
    assert response.status_code == 200 and response.json()["status"] == status


def test_audit_filter_defaults_full_query_and_invalid_values() -> None:
    service = FakeServices()
    response = request(service, "GET", "/v1/audit-events?subject_id=guest-01&mode=guarded"
        "&event_type=chat_completed&start_time=2026-08-11T10:00:00%2B08:00"
        "&end_time=2026-08-11T02:01:00Z&limit=200")
    assert response.status_code == 200 and response.json() == {"items": [], "next_cursor": None}
    filters = service.calls[0][1]
    assert type(filters) is AuditEventFilter and filters.limit == 200
    assert filters.start_time == NOW
    for suffix in ("?limit=0", "?limit=01x", "?mode=wrong", "?limit=1&limit=2",
                   f"?unknown={RAW}", "?start_time=2026-08-11T00:00:00"):
        _assert_problem(request(FakeServices(), "GET", "/v1/audit-events" + suffix),
                        "invalid_request")


def test_report_json_html_accept_ignored_and_four_service_errors() -> None:
    service = FakeServices()
    response = request(service, "GET", f"/v1/reports/{RUN_ID}",
                       headers={"accept": "text/html"})
    assert response.status_code == 200 and response.content == service.report_value.canonical_json
    assert response.headers["content-type"].startswith("application/json")

    injection = "</pre><script>" + RAW + "</script>"
    service.report_value = _stored_report(injection=injection)
    first = request(service, "GET", f"/v1/reports/{RUN_ID}?format=html",
                    headers={"accept": "application/json"})
    second = request(service, "GET", f"/v1/reports/{RUN_ID}?format=html")
    assert first.status_code == 200 and first.content == second.content
    assert first.headers["content-type"] == "text/html; charset=utf-8"
    assert b"<script>" not in first.content and b"&lt;script&gt;" in first.content
    for code in ("run_not_found", "report_not_ready", "report_unavailable", "storage_unavailable"):
        class ErrorService(FakeServices):
            async def get_report(self, run_id): raise ServiceError(code, trace_id=TRACE_ID)
        response = request(ErrorService(), "GET", f"/v1/reports/{RUN_ID}")
        _assert_problem(response, code)
        assert response.json()["trace_id"] == TRACE_ID


def test_report_rejects_format_binding_and_forged_stored_report() -> None:
    _assert_problem(request(FakeServices(), "GET", f"/v1/reports/{RUN_ID}?format=xml"),
                    "invalid_request")
    service = FakeServices()
    safe = service.report_value
    service.report_value = StoredReport.model_construct(
        run_id=RUN_ID, report_id=safe.report_id, generated_at=NOW,
        sha256=safe.sha256, canonical_json=safe.canonical_json + RAW.encode())
    response = request(service, "GET", f"/v1/reports/{RUN_ID}")
    _assert_problem(response, "internal_error")
    assert RAW not in response.text


@pytest.mark.parametrize("status,expected", [("healthy", 200), ("degraded", 200),
                                               ("unhealthy", 503)])
def test_health_statuses_are_service_supplied_and_revalidated(status, expected) -> None:
    service = FakeServices(); service.health_value = _health(status)
    response = request(service, "GET", "/health")
    assert response.status_code == expected and response.json()["status"] == status
    assert service.calls == [("health", None)]
    service = FakeServices()
    service.health_value = {**_health().model_dump(mode="python"), "extra": RAW}
    response = request(service, "GET", "/health")
    _assert_problem(response, "internal_error")
    assert RAW not in response.text


def test_service_exceptions_are_minimized_and_cancellation_propagates() -> None:
    class RawService(FakeServices):
        async def chat(self, request): raise RuntimeError(RAW)
    response = request(RawService(), "POST", "/v1/chat",
        json={"subject_id": "guest-01", "question": RAW, "mode": "baseline",
              "corpus_version": "synthetic-v1"})
    _assert_problem(response, "internal_error")
    assert RAW not in response.text

    class WrongOperationErrorService(FakeServices):
        async def chat(self, request): raise PublicProblem("run_not_found", TRACE_ID)
    response = request(WrongOperationErrorService(), "POST", "/v1/chat",
        json={"subject_id": "guest-01", "question": "q", "mode": "baseline",
              "corpus_version": "synthetic-v1"})
    _assert_problem(response, "internal_error")
    assert response.json()["trace_id"] != TRACE_ID

    class CancelService(FakeServices):
        async def health(self): raise asyncio.CancelledError()
    async def cancelled() -> None:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app(CancelService())),
                                     base_url="http://test") as client:
            with pytest.raises(asyncio.CancelledError): await client.get("/health")
    asyncio.run(cancelled())


@pytest.mark.parametrize("error,code", [
    (OllamaAdapterError(OllamaErrorCode.MODEL_TIMEOUT), "model_timeout"),
    (RagPlanningError(RagPlanningErrorCode.SUBJECT_NOT_FOUND), "subject_not_found"),
])
def test_fixed_domain_enum_errors_retain_public_code(error, code) -> None:
    class ErrorService(FakeServices):
        async def chat(self, request): raise error
    response = request(ErrorService(), "POST", "/v1/chat",
        json={"subject_id": "guest-01", "question": "q", "mode": "baseline",
              "corpus_version": "synthetic-v1"})
    _assert_problem(response, code)


def test_import_and_factory_do_not_touch_external_dependencies(monkeypatch) -> None:
    schema = json.loads((PROJECT_ROOT / "docs/contracts/report.schema.json").read_text("utf-8"))
    monkeypatch.setattr("socket.socket.connect", lambda *args, **kwargs: pytest.fail("network"))
    monkeypatch.setattr("sqlite3.connect", lambda *args, **kwargs: pytest.fail("database"))
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: pytest.fail("file"))
    app = create_app(FakeServices(), ReportContract(schema))
    assert len(app.routes) == 6
