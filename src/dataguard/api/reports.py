"""Injected report contract validation and deterministic standalone HTML rendering."""

from __future__ import annotations

import hashlib
import html
import json
from dataclasses import dataclass
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from dataguard.storage import StoredReport
from dataguard.validation import validate_report_semantics

MAX_HTML_BYTES = 32 * 1024 * 1024
_TOKEN = object()


@dataclass(frozen=True, slots=True, repr=False)
class ValidatedReport:
    _canonical_json: bytes
    _token: object

    def __post_init__(self) -> None:
        if self._token is not _TOKEN:
            raise ValueError("validated report construction is controlled")

    def as_mapping(self) -> dict[str, Any]:
        return json.loads(self._canonical_json)

    def json_bytes(self) -> bytes:
        return self._canonical_json

    def __repr__(self) -> str:
        return "ValidatedReport()"


class ReportContract:
    __slots__ = ("_validator",)

    def __init__(self, schema: Mapping[str, Any]) -> None:
        if type(schema) is not dict:
            raise ValueError("report contract is invalid")
        safe = json.loads(json.dumps(schema, allow_nan=False))
        Draft202012Validator.check_schema(safe)
        self._validator = Draft202012Validator(safe, format_checker=FormatChecker())

    def __repr__(self) -> str:
        return "ReportContract()"

    def validate(self, stored: StoredReport) -> ValidatedReport:
        try:
            if type(stored) is not StoredReport:
                raise ValueError("stored report type")
            safe_stored = StoredReport.model_validate(stored.model_dump(mode="python"))
            pairs: list[tuple[str, Any]] = []
            def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
                result: dict[str, Any] = {}
                for key, value in items:
                    if key in result: raise ValueError("duplicate report key")
                    result[key] = value
                return result
            mapping = json.loads(safe_stored.canonical_json.decode("utf-8"), object_pairs_hook=unique)
            if type(mapping) is not dict or list(self._validator.iter_errors(mapping)):
                raise ValueError("report schema")
            if validate_report_semantics(mapping):
                raise ValueError("report semantics")
            canonical = json.dumps(mapping, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
            if (canonical != safe_stored.canonical_json
                    or hashlib.sha256(canonical).hexdigest() != safe_stored.sha256
                    or mapping["run_id"] != safe_stored.run_id
                    or mapping["report_id"] != safe_stored.report_id):
                raise ValueError("report binding")
            return ValidatedReport(canonical, _TOKEN)
        except Exception:
            raise ValueError("stored report is invalid") from None


def render_report_html(report: ValidatedReport) -> str:
    try:
        if type(report) is not ValidatedReport or report._token is not _TOKEN:
            raise ValueError("report handle")
        pretty = json.dumps(report.as_mapping(), ensure_ascii=False, sort_keys=True,
                            indent=2, allow_nan=False)
        escaped = html.escape(pretty, quote=True)
        rendered = ("<!doctype html><html><head><meta charset=\"utf-8\">"
                    "<title>DataGuard Evaluation Report</title></head><body>"
                    "<h1>DataGuard Evaluation Report</h1><pre>" + escaped
                    + "</pre></body></html>")
        if len(rendered.encode("utf-8")) > MAX_HTML_BYTES:
            raise ValueError("rendered report exceeds limit")
        return rendered
    except Exception:
        raise ValueError("report rendering failed") from None
