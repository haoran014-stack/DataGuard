"""Explicit complete-report validation and canonicalization."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError

from dataguard.validation import validate_report_semantics
from .errors import ReportValidationError, StorageError

MAX_REPORT_BYTES = 16 * 1024 * 1024


def load_report_validator(project_root: Path) -> Draft202012Validator:
    """Load the committed contract for explicit repository preparation."""

    try:
        raw = (project_root / "docs" / "contracts" / "report.schema.json").read_bytes()
        if len(raw) > 1024 * 1024 or raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw:
            raise ValueError("contract bytes")
        schema = json.loads(raw.decode("utf-8"))
        if type(schema) is not dict:
            raise ValueError("contract root")
        Draft202012Validator.check_schema(schema)
        return Draft202012Validator(schema, format_checker=FormatChecker())
    except (OSError, UnicodeError, ValueError, TypeError, json.JSONDecodeError, SchemaError):
        raise StorageError() from None


def validate_and_canonicalize_report(report: Mapping[str, Any], *, expected_run_id: str,
                                     expected_profile: str, expected_scenario_set_version: str,
                                     expected_storage_backend: str,
                                     expected_generated_at: datetime,
                                     validator: Draft202012Validator | None) -> tuple[dict[str, Any], bytes, str]:
    try:
        if validator is None or type(report) is not dict:
            raise ValueError("report boundary")
        encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8") + b"\n"
        if len(encoded) > MAX_REPORT_BYTES:
            raise ValueError("report size")
        safe = json.loads(encoded)
        if list(validator.iter_errors(safe)):
            raise ValueError("report schema")
        if (safe.get("run_id") != expected_run_id or safe.get("profile") != expected_profile
                or safe.get("run_status") != "completed"
                or safe.get("experiment", {}).get("scenario_set_version") != expected_scenario_set_version
                or safe.get("experiment", {}).get("storage_backend") != expected_storage_backend):
            raise ValueError("report binding")
        generated_at = datetime.fromisoformat(safe["generated_at"].replace("Z", "+00:00"))
        if (generated_at.tzinfo is None
                or generated_at.astimezone(timezone.utc) != expected_generated_at.astimezone(timezone.utc)):
            raise ValueError("report time binding")
        if validate_report_semantics(safe):
            raise ValueError("report semantics")
        return safe, encoded, hashlib.sha256(encoded).hexdigest()
    except ReportValidationError:
        raise
    except Exception:
        raise ReportValidationError() from None
