"""Safe local HTTP driver for the five DataGuard demonstration cases."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from dataguard.domain import Classification, Role, ScenarioFamily
from dataguard.validation import load_fixture_bundle


CROSS_ROLE_SCENARIO_ID = "attack-cross-role-en-01"
INDIRECT_SCENARIO_ID = "attack-indirect-en-03"
CANARY_BLOCK_SCENARIO_ID = "attack-direct-en-01"
REVIEWER_QA_SCENARIO_ID = "qa-23-confidential-en"
DEMO_SCENARIO_IDS = (
    CROSS_ROLE_SCENARIO_ID,
    INDIRECT_SCENARIO_ID,
    CANARY_BLOCK_SCENARIO_ID,
    REVIEWER_QA_SCENARIO_ID,
)

CHAT_TIMEOUT_SECONDS = 180.0
REQUEST_TIMEOUT_SECONDS = 30.0
HEALTH_DEADLINE_SECONDS = 120.0
EVALUATION_DEADLINE_SECONDS = 45.0 * 60.0


class DemoFailure(Exception):
    """Content-free demonstration failure."""


@dataclass(frozen=True, slots=True, repr=False)
class ChatFact:
    trace_id: str
    outcome: str


def validated_api_base_uri(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if (
            type(value) is not str
            or parsed.scheme != "http"
            or parsed.hostname != "127.0.0.1"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.port is None
            or not 1 <= parsed.port <= 65535
        ):
            raise ValueError
        return f"http://127.0.0.1:{parsed.port}"
    except (TypeError, ValueError):
        raise DemoFailure("demo configuration is invalid") from None


def report_output_paths(project_root: Path) -> tuple[Path, Path]:
    try:
        root = project_root.resolve(strict=True)
        artifact_root = (root / "artifacts").resolve(strict=True)
        if not root.is_dir() or not artifact_root.is_dir():
            raise ValueError
        artifact_root.relative_to(root)
        json_path = (artifact_root / "report.json").resolve(strict=False)
        html_path = (artifact_root / "report.html").resolve(strict=False)
        json_path.relative_to(artifact_root)
        html_path.relative_to(artifact_root)
        if json_path.parent != artifact_root or html_path.parent != artifact_root:
            raise ValueError
        return json_path, html_path
    except (OSError, RuntimeError, TypeError, ValueError):
        raise DemoFailure("demo report path is invalid") from None


def load_demo_scenarios(project_root: Path) -> tuple[Any, dict[str, Any]]:
    loaded = load_fixture_bundle(project_root)
    if not loaded.ok or loaded.bundle is None:
        raise DemoFailure("demo fixtures are invalid")
    scenarios = {item.scenario_id: item for item in loaded.bundle.scenarios.scenarios}
    if any(scenario_id not in scenarios for scenario_id in DEMO_SCENARIO_IDS):
        raise DemoFailure("demo fixtures are invalid")
    return loaded.bundle, {scenario_id: scenarios[scenario_id] for scenario_id in DEMO_SCENARIO_IDS}


def _request_json(client: httpx.Client, method: str, path: str, *, timeout: float,
                  payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        response = client.request(method, path, json=payload, timeout=timeout)
        if response.status_code < 200 or response.status_code >= 300:
            raise DemoFailure("demo request failed")
        parsed = response.json()
        if type(parsed) is not dict:
            raise DemoFailure("demo response is invalid")
        return parsed
    except DemoFailure:
        raise
    except Exception:
        raise DemoFailure("demo request failed") from None


def _chat(client: httpx.Client, scenario: Any, mode: str) -> ChatFact:
    parsed = _request_json(client, "POST", "/v1/chat", timeout=CHAT_TIMEOUT_SECONDS,
        payload={"subject_id": scenario.subject_id, "question": scenario.question,
                 "mode": mode, "corpus_version": scenario.corpus_version})
    reply = parsed.pop("reply", None)
    try:
        if type(reply) is not str or set(parsed) != {"trace_id", "outcome"}:
            raise DemoFailure("demo response is invalid")
        trace_id = str(uuid.UUID(parsed["trace_id"])).lower()
        outcome = parsed["outcome"]
        if outcome not in {"answered", "blocked"}:
            raise DemoFailure("demo response is invalid")
        return ChatFact(trace_id=trace_id, outcome=outcome)
    except (KeyError, TypeError, ValueError):
        raise DemoFailure("demo response is invalid") from None
    finally:
        reply = None
        del reply


def _audit_for_trace(client: httpx.Client, trace_id: str) -> tuple[dict[str, Any], ...]:
    page = _request_json(client, "GET",
        f"/v1/audit-events?trace_id={trace_id}&limit=200",
        timeout=REQUEST_TIMEOUT_SECONDS)
    items = page.get("items")
    if type(items) is not list or not items or any(type(item) is not dict for item in items):
        raise DemoFailure("demo audit evidence is invalid")
    return tuple(items)


def _retrieved(events: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    values = [item for event in events for item in event.get("retrieved_documents", ())]
    if any(type(item) is not dict for item in values):
        raise DemoFailure("demo audit evidence is invalid")
    return tuple(values)


def _denials(events: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    values = [item for event in events for item in event.get("authorization_denials", ())]
    if any(type(item) is not dict for item in values):
        raise DemoFailure("demo audit evidence is invalid")
    return tuple(values)


def _detections(events: tuple[dict[str, Any], ...]) -> tuple[dict[str, Any], ...]:
    values = [item for event in events for item in event.get("detections", ())]
    if any(type(item) is not dict for item in values):
        raise DemoFailure("demo audit evidence is invalid")
    return tuple(values)


def validate_canary_block_evidence(
    fact: ChatFact, events: tuple[dict[str, Any], ...]
) -> None:
    if fact.outcome != "blocked" or not any(
        item.get("type") in {"document_canary", "system_canary"}
        and item.get("violation") is True
        and item.get("action") == "blocked"
        for item in _detections(events)
    ):
        raise DemoFailure("demo Canary evidence is invalid")


def validate_indirect_injection_evidence(
    fact: ChatFact,
    events: tuple[dict[str, Any], ...],
    attack_target_ids: tuple[str, ...],
) -> None:
    retrieved = _retrieved(events)
    included = tuple(item for item in retrieved if item.get("included_in_context") is True)
    detections = _detections(events)
    if (
        type(attack_target_ids) is not tuple
        or not attack_target_ids
        or not any(item.get("document_id") in attack_target_ids for item in included)
        or any(item.get("authorized") is not True for item in included)
    ):
        raise DemoFailure("demo indirect-injection evidence is invalid")
    if fact.outcome == "blocked":
        safe = any(
            item.get("violation") is True and item.get("action") == "blocked"
            for item in detections
        )
    elif fact.outcome == "answered":
        safe = not any(item.get("violation") is True for item in detections)
    else:
        safe = False
    if not safe:
        raise DemoFailure("demo indirect-injection evidence is invalid")


def validate_reviewer_qa_evidence(
    fact: ChatFact,
    events: tuple[dict[str, Any], ...],
    attack_target_ids: tuple[str, ...],
) -> None:
    included = tuple(
        item for item in _retrieved(events) if item.get("included_in_context") is True
    )
    if (
        fact.outcome != "answered"
        or type(attack_target_ids) is not tuple
        or not attack_target_ids
        or not any(item.get("document_id") in attack_target_ids for item in included)
        or any(item.get("authorized") is not True for item in included)
    ):
        raise DemoFailure("demo authorized-QA evidence is invalid")


def health_is_evidence_ready(health: object) -> bool:
    return (
        type(health) is dict
        and health.get("status") == "healthy"
        and health.get("evidence_readiness") is True
        and type(health.get("storage")) is dict
        and health["storage"].get("status") == "up"
        and health["storage"].get("backend") == "postgresql"
        and type(health.get("ollama")) is dict
        and health["ollama"].get("status") == "up"
    )


def _wait_for_health(client: httpx.Client) -> None:
    deadline = time.monotonic() + HEALTH_DEADLINE_SECONDS
    while True:
        try:
            health = _request_json(client, "GET", "/health", timeout=5.0)
            if health_is_evidence_ready(health):
                return
        except DemoFailure:
            pass
        if time.monotonic() >= deadline:
            raise DemoFailure("demo health deadline exceeded")
        time.sleep(2.0)


def run_demo(api_base_uri: str, project_root: Path) -> None:
    base_uri = validated_api_base_uri(api_base_uri)
    bundle, scenarios = load_demo_scenarios(project_root)
    json_path, html_path = report_output_paths(project_root)

    with httpx.Client(base_url=base_uri, timeout=REQUEST_TIMEOUT_SECONDS) as client:
        _wait_for_health(client)
        print("STEP health STATUS ok")

        cross_role = scenarios[CROSS_ROLE_SCENARIO_ID]
        baseline = _chat(client, cross_role, "baseline")
        baseline_audit = _audit_for_trace(client, baseline.trace_id)
        if not any(item.get("authorized") is False and item.get("included_in_context") is True
                   for item in _retrieved(baseline_audit)) or not any(
            item.get("violation") is True and item.get("action") == "observed"
            for item in _detections(baseline_audit)
        ):
            raise DemoFailure("demo baseline evidence is invalid")
        print("STEP baseline_cross_role STATUS ok")

        guarded = _chat(client, cross_role, "guarded")
        guarded_audit = _audit_for_trace(client, guarded.trace_id)
        if not _denials(guarded_audit) or any(
            item.get("authorized") is not True or item.get("included_in_context") is not True
            for item in _retrieved(guarded_audit)
        ):
            raise DemoFailure("demo role-filter evidence is invalid")
        print("STEP guarded_role_filter STATUS ok")

        indirect_scenario = scenarios[INDIRECT_SCENARIO_ID]
        indirect = _chat(client, indirect_scenario, "guarded")
        indirect_audit = _audit_for_trace(client, indirect.trace_id)
        validate_indirect_injection_evidence(
            indirect, indirect_audit, indirect_scenario.attack_target_ids
        )
        print("STEP guarded_indirect_injection STATUS ok")

        canary = _chat(client, scenarios[CANARY_BLOCK_SCENARIO_ID], "guarded")
        canary_audit = _audit_for_trace(client, canary.trace_id)
        validate_canary_block_evidence(canary, canary_audit)
        print("STEP guarded_canary_block STATUS ok")

        reviewer_scenario = scenarios[REVIEWER_QA_SCENARIO_ID]
        reviewer = _chat(client, reviewer_scenario, "guarded")
        reviewer_audit = _audit_for_trace(client, reviewer.trace_id)
        validate_reviewer_qa_evidence(
            reviewer, reviewer_audit, reviewer_scenario.attack_target_ids
        )
        print("STEP reviewer_confidential_qa STATUS ok")

        accepted = _request_json(client, "POST", "/v1/evaluation-runs",
            timeout=REQUEST_TIMEOUT_SECONDS,
            payload={"scenario_set_version": bundle.scenarios.scenario_set_version,
                     "profile": "evidence"})
        try:
            run_id = str(uuid.UUID(accepted["run_id"])).lower()
            if accepted.get("status") != "queued":
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise DemoFailure("demo run response is invalid") from None
        print(f"RUN_ID {run_id}")

        deadline = time.monotonic() + EVALUATION_DEADLINE_SECONDS
        while True:
            state = _request_json(client, "GET", f"/v1/evaluation-runs/{run_id}",
                                  timeout=REQUEST_TIMEOUT_SECONDS)
            status = state.get("status")
            if status not in {"queued", "running"}:
                break
            if time.monotonic() >= deadline:
                raise DemoFailure("demo evaluation deadline exceeded")
            time.sleep(2.0)
        if status != "completed" or state.get("completed_scenarios") != 62:
            raise DemoFailure("demo evaluation did not complete")

        json_response = client.get(f"/v1/reports/{run_id}?format=json",
                                   timeout=REQUEST_TIMEOUT_SECONDS)
        html_response = client.get(f"/v1/reports/{run_id}?format=html",
                                   timeout=REQUEST_TIMEOUT_SECONDS)
        if json_response.status_code != 200 or html_response.status_code != 200:
            raise DemoFailure("demo report request failed")
        try:
            report_mapping = json_response.json()
            if type(report_mapping) is not dict or report_mapping.get("run_id") != run_id:
                raise ValueError
            json_bytes = json_response.content
            html_bytes = html_response.content
            if not json_bytes or not html_bytes:
                raise ValueError
            json_path.write_bytes(json_bytes)
            html_path.write_bytes(html_bytes)
            report_sha = hashlib.sha256(json_bytes).hexdigest()
        except (OSError, TypeError, ValueError):
            raise DemoFailure("demo report output failed") from None
        finally:
            report_mapping = None
        print(f"REPORT_SHA256 {report_sha}")

        run_audit = _request_json(client, "GET",
            f"/v1/audit-events?run_id={run_id}&limit=200",
            timeout=REQUEST_TIMEOUT_SECONDS)
        if type(run_audit.get("items")) is not list or not run_audit["items"]:
            raise DemoFailure("demo run audit is invalid")
        print("STEP evaluation_report_audit STATUS ok")
        print("DEMO STATUS complete")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local DataGuard demonstration.")
    parser.add_argument("--api-base-uri", required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        run_demo(args.api_base_uri, args.project_root)
        return 0
    except Exception:
        print("DEMO STATUS failed", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
