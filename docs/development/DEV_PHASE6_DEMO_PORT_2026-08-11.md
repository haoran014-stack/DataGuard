# Phase 6 development record - configurable demo API port

## Scope

- Added a validated `ApiPort` parameter to the Windows demo, defaulting to
  `8000` and accepting only `1..65535`.
- The script exports the selected value as `DATAGUARD_API_PORT` for Compose and
  constructs one loopback-only API base URI used by health, chat, run, report,
  and audit requests.
- Container-internal port and healthcheck behavior remain on port `8000`.
- No real `.env` content or credential was read or printed. No container, model,
  or evaluation was started, and no commit or push was performed.

## Files

- `scripts/demo.ps1`: parameter, Compose environment handoff, and single base URI.
- `tests/unit/test_delivery_files.py`: static closed-boundary regression.
- `README.md`: default and `-ApiPort 18000` conflict example.

## Development checks

| Command | Exit | Evidence |
|---|---:|---|
| `.\.venv\Scripts\python -m pytest tests\unit\test_delivery_files.py -q` | `0` | `6 passed in 0.08s`. |
| PowerShell `System.Management.Automation.Language.Parser.ParseFile` | `0` | `POWERSHELL_PARSE_OK`. |
| `git diff --check` | `0` | Whitespace validation only; no script execution. |

This record is development evidence only, not independent test or architecture
acceptance.
