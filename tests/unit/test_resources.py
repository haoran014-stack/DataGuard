from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from importlib import resources
from pathlib import Path
from uuid import UUID

import pytest

from dataguard.resources import (
    FIXED_BLOCKED_REPLY,
    RESOURCE_NAMES,
    ResourceLoadError,
    load_security_resources,
    parse_resource_bytes,
)
from dataguard.validation import load_fixture_bundle


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _resource_bytes() -> dict[str, bytes]:
    package = resources.files("dataguard.resources")
    return {name: package.joinpath(name).read_bytes() for name in RESOURCE_NAMES}


def test_installed_package_resources_load_with_stable_exact_byte_digests() -> None:
    raw = _resource_bytes()
    loaded = load_security_resources()

    assert loaded.artifact_digests() == {
        "system_prompt": hashlib.sha256(raw[RESOURCE_NAMES[0]]).hexdigest(),
        "baseline_prompt_template": hashlib.sha256(raw[RESOURCE_NAMES[1]]).hexdigest(),
        "guarded_prompt_template": hashlib.sha256(raw[RESOURCE_NAMES[2]]).hexdigest(),
        "guard_policy": hashlib.sha256(raw[RESOURCE_NAMES[3]]).hexdigest(),
        "detector": hashlib.sha256(raw[RESOURCE_NAMES[4]]).hexdigest(),
    }
    assert all(
        resources.files("dataguard.resources").joinpath(name).is_file()
        for name in RESOURCE_NAMES
    )


def test_system_canary_is_unique_synthetic_opaque_and_not_a_document_canary() -> None:
    raw = _resource_bytes()
    loaded = load_security_resources()
    system = loaded.system_prompt.value
    marker = system.system_canary_literal  # type: ignore[union-attr]
    bundle = load_fixture_bundle(PROJECT_ROOT).bundle
    if bundle is None:
        pytest.fail("accepted fixture bundle did not load")

    valid = (
        sum(content.decode("utf-8").count(marker) for content in raw.values()) == 1
        and str(UUID(str(system.system_canary_evidence_id)))  # type: ignore[union-attr]
        == str(system.system_canary_evidence_id)  # type: ignore[union-attr]
        and str(system.system_canary_evidence_id)  # type: ignore[union-attr]
        not in {
            evidence_id
            for document in bundle.corpus.documents
            for evidence_id in (
                *(canary.canary_id for canary in document.canaries),
                *(fragment.fragment_id for fragment in document.protected_fragments),
            )
        }
        and all(
            canary.value != marker
            for document in bundle.corpus.documents
            for canary in document.canaries
        )
    )
    if not valid:
        pytest.fail("reviewed synthetic system Canary boundary is invalid")

    reviewed_resource = PROJECT_ROOT / "src/dataguard/resources/system-prompt.v1.yaml"
    for path in PROJECT_ROOT.rglob("*"):
        if (
            not path.is_file()
            or path == reviewed_resource
            or any(part in {".git", ".venv", ".pytest_cache", "__pycache__"} for part in path.parts)
        ):
            continue
        if path.suffix.lower() not in {".py", ".md", ".yaml", ".yml", ".json", ".toml"}:
            continue
        if marker in path.read_text(encoding="utf-8"):
            pytest.fail("system Canary literal escaped its reviewed resource")


def test_locked_policy_detector_and_template_declarations_match_architecture() -> None:
    loaded = load_security_resources()
    policy = loaded.guard_policy.value
    detector = loaded.detector.value
    baseline = loaded.baseline_prompt.value
    guarded = loaded.guarded_prompt.value

    assert policy.generation_model == "qwen2.5:3b-instruct"  # type: ignore[union-attr]
    assert policy.embedding_model == "qwen3-embedding:0.6b"  # type: ignore[union-attr]
    assert policy.guarded_fixed_reply == FIXED_BLOCKED_REPLY  # type: ignore[union-attr]
    assert policy.settings.model_dump() == {  # type: ignore[union-attr]
        "temperature": 0,
        "seed": 42,
        "generation_top_k": 20,
        "top_p": 0.9,
        "num_ctx": 8192,
        "num_predict": 512,
        "retrieval_top_k": 4,
        "stream": False,
    }
    assert detector.normalization == (  # type: ignore[union-attr]
        "NFKC",
        "casefold",
        "remove_zero_width",
        "normalize_whitespace",
    )
    assert detector.zero_width_codepoints == (  # type: ignore[union-attr]
        "U+200B",
        "U+200C",
        "U+200D",
        "U+2060",
        "U+FEFF",
    )
    assert detector.guarded_fixed_reply == FIXED_BLOCKED_REPLY  # type: ignore[union-attr]
    assert baseline.placeholders == (  # type: ignore[union-attr]
        "system_prompt",
        "documents_text",
        "question",
    )
    assert guarded.placeholders == (  # type: ignore[union-attr]
        "system_prompt",
        "documents_json",
        "question",
    )
    baseline_text = baseline.template.casefold()  # type: ignore[union-attr]
    self_neutralizing_terms = (
        "untrusted",
        "ignore document",
        "do not follow",
        "do not obey",
        "不可信",
        "忽略文档",
        "不要遵循",
        "不得遵循",
        "不要服从",
        "不得服从",
        "不得执行",
    )
    assert all(term not in baseline_text for term in self_neutralizing_terms)
    assert not hasattr(baseline, "render")
    assert not hasattr(guarded, "render")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: b"\xef\xbb\xbf" + raw,
        lambda raw: raw.replace(b"\n", b"\r\n", 1),
        lambda raw: raw + b'unknown_field: "RAW_RESOURCE_INJECTION_SHOULD_NOT_APPEAR"\n',
        lambda raw: b'version: "9.9"\n' + raw,
    ],
)
def test_parser_rejects_bom_cr_unknown_and_duplicate_yaml_without_echo(mutate: object) -> None:
    raw = _resource_bytes()["baseline-prompt.v1.yaml"]
    with pytest.raises(ResourceLoadError) as captured:
        parse_resource_bytes("baseline-prompt.v1.yaml", mutate(raw))  # type: ignore[operator]

    rendered = repr(captured.value.as_dict())
    assert "RAW_RESOURCE_INJECTION_SHOULD_NOT_APPEAR" not in rendered
    assert set(captured.value.as_dict()) == {"code", "message"}


def test_loader_rejects_missing_resource_with_content_free_error() -> None:
    raw = _resource_bytes()
    raw.pop("detector.v1.yaml")

    with pytest.raises(ResourceLoadError) as captured:
        load_security_resources(raw.__getitem__)

    assert captured.value.code == "resource_unavailable"
    assert set(captured.value.as_dict()) == {"code", "message"}


def test_loader_rejects_fixed_constant_drift_without_echo() -> None:
    raw = _resource_bytes()
    sentinel = b"RAW_RESOURCE_INJECTION_SHOULD_NOT_APPEAR"
    raw["guard-policy.v1.yaml"] = raw["guard-policy.v1.yaml"].replace(
        b"qwen2.5:3b-instruct",
        sentinel,
    )

    with pytest.raises(ResourceLoadError) as captured:
        load_security_resources(raw.__getitem__)

    assert sentinel.decode("ascii") not in repr(captured.value.as_dict())


def test_loader_rejects_system_canary_reuse_dynamically_without_copying_literal() -> None:
    raw = _resource_bytes()
    loaded = load_security_resources(raw.__getitem__)
    marker = loaded.system_prompt.value.system_canary_literal  # type: ignore[union-attr]
    raw["baseline-prompt.v1.yaml"] += f"\nreviewed_marker_reuse: {marker}\n".encode()

    with pytest.raises(ResourceLoadError) as captured:
        load_security_resources(raw.__getitem__)

    assert marker not in repr(captured.value.as_dict())


def test_resource_package_import_performs_no_io() -> None:
    script = """
import importlib.resources

def forbidden(*args, **kwargs):
    raise RuntimeError("resource I/O attempted")

importlib.resources.files = forbidden
import dataguard.resources
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
