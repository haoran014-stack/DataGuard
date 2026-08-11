"""Contract-bound, low-cardinality in-process metrics without a public route."""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass
from typing import Any, Mapping

import yaml
from yaml.nodes import MappingNode


_TOP_LEVEL_KEYS = frozenset({"version", "prefix", "scope", "definitions", "rules",
    "enums", "metrics", "derived_report_measures", "eligibility_rule",
    "fixed_distribution", "v1_evidence_gates"})
_FORBIDDEN_LABELS = ("subject_id", "trace_id", "run_id", "scenario_id", "document_id",
    "evidence_id", "model_digest", "free_form_error")
_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
_METRIC_SHAPES = (
    ("dataguard_chat_requests_total", "counter", "requests", ("mode", "resolved_role", "outcome")),
    ("dataguard_chat_duration_seconds", "histogram", "seconds", ("mode", "outcome")),
    ("dataguard_retrieved_documents_total", "counter", "documents", ("mode", "authorization")),
    ("dataguard_output_detector_matches_total", "counter", "matches", ("mode", "detection_type", "detector_action")),
    ("dataguard_attack_attempts_total", "counter", "scenarios", ("mode", "attack_family")),
    ("dataguard_attack_successes_total", "counter", "scenarios", ("mode", "attack_family")),
    ("dataguard_attack_deliveries_total", "counter", "scenarios", ("mode", "attack_family")),
    ("dataguard_unauthorized_context_documents_total", "counter", "documents", ("mode",)),
    ("dataguard_retrieval_authorization_violation_scenarios_total", "counter", "scenarios", ("mode",)),
    ("dataguard_scenario_judgments_total", "counter", "mode_results", ("mode", "scenario_kind", "judgment")),
    ("dataguard_authorized_qa_results_total", "counter", "scenarios", ("mode", "result")),
    ("dataguard_blocked_baseline_attacks_total", "counter", "paired_scenarios", ()),
    ("dataguard_guard_interventions_total", "counter", "interventions", ("prevention_stage",)),
    ("dataguard_evaluation_runs_total", "counter", "runs", ("profile", "status", "storage_backend")),
    ("dataguard_evaluation_run_duration_seconds", "histogram", "seconds", ("profile", "terminal_status")),
    ("dataguard_ollama_requests_total", "counter", "requests", ("operation", "result")),
    ("dataguard_evidence_write_failures_total", "counter", "failures", ("backend", "record_type")),
)
_ENUMS = {
    "mode": ("baseline", "guarded"),
    "role": ("guest", "employee", "security_reviewer"),
    "chat_outcome": ("answered", "blocked"),
    "evaluation_outcome": ("answered", "blocked", "failed"),
    "attack_family": ("direct_prompt_injection", "indirect_document_injection",
                      "cross_role_retrieval", "system_prompt_inducement"),
    "detection_type": ("document_canary", "system_canary", "unauthorized_protected_fragment"),
    "detector_action": ("observed", "blocked"),
    "scenario_judgment": ("attack_succeeded", "attack_prevented", "authorized_qa_pass",
                          "authorized_qa_fail", "false_rejection", "indeterminate"),
}
_INLINE_LABELS = {
    ("dataguard_retrieved_documents_total", "authorization"): ("authorized", "unauthorized"),
    ("dataguard_scenario_judgments_total", "scenario_kind"): ("attack", "authorized_qa"),
    ("dataguard_authorized_qa_results_total", "result"): ("pass", "fail", "false_rejection", "indeterminate"),
    ("dataguard_guard_interventions_total", "prevention_stage"): ("role_filter", "prompt_isolation", "output_gate"),
    ("dataguard_evaluation_runs_total", "profile"): ("exploratory", "evidence"),
    ("dataguard_evaluation_runs_total", "status"): ("queued", "running", "completed", "failed", "interrupted"),
    ("dataguard_evaluation_runs_total", "storage_backend"): ("sqlite", "postgresql"),
    ("dataguard_evaluation_run_duration_seconds", "profile"): ("exploratory", "evidence"),
    ("dataguard_evaluation_run_duration_seconds", "terminal_status"): ("completed", "failed", "interrupted"),
    ("dataguard_ollama_requests_total", "operation"): ("embedding", "generation"),
    ("dataguard_ollama_requests_total", "result"): ("success", "timeout", "unavailable", "protocol_error"),
    ("dataguard_evidence_write_failures_total", "backend"): ("sqlite", "postgresql"),
    ("dataguard_evidence_write_failures_total", "record_type"): ("audit_event", "run_state", "report"),
}
_ENUM_REFS = {
    ("dataguard_chat_requests_total", "mode"): "enum.mode",
    ("dataguard_chat_requests_total", "resolved_role"): "enum.role",
    ("dataguard_chat_requests_total", "outcome"): "enum.chat_outcome",
    ("dataguard_chat_duration_seconds", "mode"): "enum.mode",
    ("dataguard_chat_duration_seconds", "outcome"): "enum.chat_outcome",
    ("dataguard_retrieved_documents_total", "mode"): "enum.mode",
    ("dataguard_output_detector_matches_total", "mode"): "enum.mode",
    ("dataguard_output_detector_matches_total", "detection_type"): "enum.detection_type",
    ("dataguard_output_detector_matches_total", "detector_action"): "enum.detector_action",
    ("dataguard_attack_attempts_total", "mode"): "enum.mode",
    ("dataguard_attack_attempts_total", "attack_family"): "enum.attack_family",
    ("dataguard_attack_successes_total", "mode"): "enum.mode",
    ("dataguard_attack_successes_total", "attack_family"): "enum.attack_family",
    ("dataguard_attack_deliveries_total", "mode"): "enum.mode",
    ("dataguard_attack_deliveries_total", "attack_family"): "enum.attack_family",
    ("dataguard_unauthorized_context_documents_total", "mode"): "enum.mode",
    ("dataguard_retrieval_authorization_violation_scenarios_total", "mode"): "enum.mode",
    ("dataguard_scenario_judgments_total", "mode"): "enum.mode",
    ("dataguard_scenario_judgments_total", "judgment"): "enum.scenario_judgment",
    ("dataguard_authorized_qa_results_total", "mode"): "enum.mode",
}


class MetricsError(ValueError):
    def __init__(self) -> None:
        super().__init__("Metric update does not match the fixed contract.")


class _UniqueLoader(yaml.SafeLoader):
    def construct_mapping(self, node: MappingNode, deep: bool = False):
        self.flatten_mapping(node)
        keys = []
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=False)
            if key in keys: raise MetricsError()
            keys.append(key)
        return super().construct_mapping(node, deep=deep)


def load_metrics_contract(raw: bytes) -> dict[str, Any]:
    """Parse the committed LF/UTF-8 catalog while rejecting duplicate YAML keys."""

    try:
        if type(raw) is not bytes or raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw:
            raise ValueError
        value = yaml.load(raw.decode("utf-8"), Loader=_UniqueLoader)
        if type(value) is not dict:
            raise ValueError
        return value
    except Exception:
        raise MetricsError() from None


@dataclass(frozen=True, slots=True, repr=False)
class _Definition:
    name: str
    type: str
    help: str
    labels: tuple[tuple[str, tuple[str, ...]], ...]


class MetricsRegistry:
    """Validate every metric and label value before bounded aggregation."""

    __slots__ = ("_definitions", "_buckets", "_values", "_lock")

    def __init__(self, contract: Mapping[str, Any]) -> None:
        try:
            if (type(contract) is not dict or set(contract) != _TOP_LEVEL_KEYS
                    or contract.get("version") != 1):
                raise ValueError
            if (contract.get("prefix") != "dataguard"
                    or contract.get("scope") != "local_synthetic_rag_experiment"
                    or contract["rules"].get("raw_question_document_context_prompt_reply_forbidden") is not True
                    or contract["rules"].get("canary_or_protected_fragment_literal_forbidden") is not True):
                raise ValueError
            enums = contract["enums"]
            if enums != {key: list(values) for key, values in _ENUMS.items()}:
                raise ValueError
            definitions: dict[str, _Definition] = {}
            metrics = contract["metrics"]
            if type(metrics) is not list or len(metrics) != len(_METRIC_SHAPES):
                raise ValueError
            for item, expected_shape in zip(metrics, _METRIC_SHAPES, strict=True):
                if (type(item) is not dict or set(item) != {"name", "type", "unit", "help", "labels"}
                        or item["type"] not in {"counter", "histogram"}
                        or not item["name"].startswith("dataguard_")
                        or item["name"] in definitions):
                    raise ValueError
                if ((item["name"], item["type"], item["unit"], tuple(item["labels"])) != expected_shape
                        or type(item["help"]) is not str
                        or not item["help"].strip()):
                    raise ValueError
                labels = []
                for label, source in item["labels"].items():
                    if label in contract["rules"]["forbidden_labels"]:
                        raise ValueError
                    key = (item["name"], label)
                    if key in _ENUM_REFS:
                        expected_source = _ENUM_REFS[key]
                        if source != expected_source: raise ValueError
                        allowed = list(_ENUMS[expected_source.removeprefix("enum.")])
                    else:
                        expected_values = _INLINE_LABELS.get(key)
                        if expected_values is None or source != list(expected_values): raise ValueError
                        allowed = list(expected_values)
                    if not allowed:
                        raise ValueError
                    labels.append((label, tuple(allowed)))
                definitions[item["name"]] = _Definition(
                    item["name"], item["type"], item["help"], tuple(labels))
            buckets = tuple(float(value) for value in contract["rules"]["histogram_buckets_seconds"])
            if (buckets != _BUCKETS
                    or tuple(contract["rules"]["forbidden_labels"]) != _FORBIDDEN_LABELS):
                raise ValueError
        except Exception:
            raise MetricsError() from None
        self._definitions = definitions
        self._buckets = buckets
        self._values: dict[tuple[str, tuple[tuple[str, str], ...]], Any] = {}
        self._lock = threading.Lock()

    @property
    def metric_names(self) -> tuple[str, ...]:
        return tuple(self._definitions)

    def _key(self, name: str, labels: Mapping[str, str]) -> tuple[str, tuple[tuple[str, str], ...]]:
        definition = self._definitions.get(name)
        if definition is None or type(labels) is not dict:
            raise MetricsError()
        expected = {key: values for key, values in definition.labels}
        if set(labels) != set(expected) or any(
            type(value) is not str or value not in expected[key] for key, value in labels.items()
        ):
            raise MetricsError()
        return name, tuple((key, labels[key]) for key, _ in definition.labels)

    def increment(self, name: str, labels: dict[str, str], amount: int = 1) -> None:
        if type(amount) is not int or amount < 0:
            raise MetricsError()
        key = self._key(name, labels)
        if self._definitions[name].type != "counter":
            raise MetricsError()
        with self._lock:
            self._values[key] = self._values.get(key, 0) + amount

    def observe(self, name: str, labels: dict[str, str], seconds: float) -> None:
        if type(seconds) not in {int, float} or not math.isfinite(seconds) or seconds < 0:
            raise MetricsError()
        key = self._key(name, labels)
        if self._definitions[name].type != "histogram":
            raise MetricsError()
        with self._lock:
            count, total, buckets = self._values.get(
                key, (0, 0.0, [0] * len(self._buckets)))
            for index, bound in enumerate(self._buckets):
                if seconds <= bound:
                    buckets[index] += 1
            self._values[key] = (count + 1, total + float(seconds), buckets)

    @staticmethod
    def _labels(values: tuple[tuple[str, str], ...], extra: tuple[str, str] | None = None) -> str:
        items = (*values, *((extra,) if extra else ()))
        return "{" + ",".join(f'{key}="{value}"' for key, value in items) + "}" if items else ""

    def render_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            snapshot = dict(self._values)
        for name, definition in self._definitions.items():
            lines.extend((f"# HELP {name} {definition.help}", f"# TYPE {name} {definition.type}"))
            entries = sorted((key[1], value) for key, value in snapshot.items() if key[0] == name)
            for labels, value in entries:
                if definition.type == "counter":
                    lines.append(f"{name}{self._labels(labels)} {value}")
                else:
                    count, total, bucket_counts = value
                    for bound, bucket_count in zip(self._buckets, bucket_counts, strict=True):
                        lines.append(f"{name}_bucket{self._labels(labels, ('le', format(bound, 'g')))} {bucket_count}")
                    lines.append(f"{name}_bucket{self._labels(labels, ('le', '+Inf'))} {count}")
                    lines.append(f"{name}_sum{self._labels(labels)} {format(total, '.17g')}")
                    lines.append(f"{name}_count{self._labels(labels)} {count}")
        return "\n".join(lines) + "\n"
