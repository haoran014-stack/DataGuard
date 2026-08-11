from pathlib import Path
import copy

import pytest
import yaml

from dataguard.metrics import MetricsError, MetricsRegistry, load_metrics_contract


ROOT = Path(__file__).resolve().parents[2]


def _contract():
    return yaml.safe_load((ROOT / "docs/contracts/metrics.yaml").read_text("utf-8"))


def test_registry_matches_complete_contract_and_renders_deterministically():
    contract = _contract()
    registry = MetricsRegistry(contract)
    assert registry.metric_names == tuple(item["name"] for item in contract["metrics"])

    labels = {"mode": "guarded", "resolved_role": "guest", "outcome": "blocked"}
    registry.increment("dataguard_chat_requests_total", labels)
    registry.increment("dataguard_chat_requests_total", labels, 2)
    duration_labels = {"mode": "guarded", "outcome": "blocked"}
    registry.observe("dataguard_chat_duration_seconds", duration_labels, 0.1)
    first = registry.render_prometheus()
    assert first == registry.render_prometheus()
    assert 'dataguard_chat_requests_total{mode="guarded",resolved_role="guest",outcome="blocked"} 3' in first
    assert 'dataguard_chat_duration_seconds_count{mode="guarded",outcome="blocked"} 1' in first


@pytest.mark.parametrize("labels", [
    {"mode": "guarded", "resolved_role": "guest", "outcome": "blocked", "subject_id": "raw"},
    {"mode": "guarded", "resolved_role": "raw-high-cardinality", "outcome": "blocked"},
    {"mode": "guarded", "outcome": "blocked"},
])
def test_registry_rejects_high_cardinality_or_contract_drift(labels):
    registry = MetricsRegistry(_contract())
    with pytest.raises(MetricsError):
        registry.increment("dataguard_chat_requests_total", labels)


def test_registry_rejects_unknown_metric_and_wrong_type():
    registry = MetricsRegistry(_contract())
    with pytest.raises(MetricsError):
        registry.increment("dataguard_raw_sentinel", {})
    with pytest.raises(MetricsError):
        registry.observe("dataguard_chat_requests_total", {
            "mode": "baseline", "resolved_role": "guest", "outcome": "answered"}, 1.0)


def test_contract_loader_rejects_duplicate_keys_and_non_lf_bytes():
    with pytest.raises(MetricsError):
        load_metrics_contract(b"version: 1\nversion: 1\n")
    with pytest.raises(MetricsError):
        load_metrics_contract(b"version: 1\r\n")


@pytest.mark.parametrize("mutation", ["remove", "add", "label", "type", "bucket", "forbidden",
                                          "top", "enum_value", "inline_value", "known_unit"])
def test_registry_rejects_catalog_shape_drift(mutation):
    contract = copy.deepcopy(_contract())
    if mutation == "remove": contract["metrics"].pop()
    elif mutation == "add": contract["metrics"].append(copy.deepcopy(contract["metrics"][0]))
    elif mutation == "label": contract["metrics"][0]["labels"] = {"mode": "enum.mode"}
    elif mutation == "type": contract["metrics"][0]["type"] = "histogram"
    elif mutation == "bucket": contract["rules"]["histogram_buckets_seconds"][0] = 0.04
    elif mutation == "forbidden": contract["rules"]["forbidden_labels"].pop()
    elif mutation == "enum_value": contract["enums"]["mode"].append("raw-high-cardinality")
    elif mutation == "inline_value": contract["metrics"][2]["labels"]["authorization"].append("raw")
    elif mutation == "known_unit": contract["metrics"][0]["unit"] = "seconds"
    else: contract["extra"] = True
    with pytest.raises(MetricsError):
        MetricsRegistry(contract)
