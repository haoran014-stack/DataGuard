# Development work record: Phase 4 queued recovery fix

## Scope

- Date: 2026-08-11
- Baseline: clean `main@47959effb01059731611ec10d0afb18dd95bc46c`
- Scope: original-roadmap Phase 4 restart semantics only
- Excluded: completed 62-pair evidence, report conclusions, PostgreSQL/Docker,
  model/fixture/policy changes, commit, and push

## Product gap

The repository recovery transaction already preserved persisted `queued` runs
and atomically changed pre-restart `running` runs to `interrupted` with
`failure_code=internal_error` and no report. Production startup, however,
created a new in-process scheduler without enumerating those persisted queued
runs. A queued run therefore remained queryable but never resumed execution,
which contradicted the locked Phase 4 restart contract.

## Minimal fix

- The internal repository now exposes `list_queued_runs()`, returning only
  queued runs in deterministic `(created_at, run_id)` FIFO order after the same
  storage/schema validation as other reads.
- Once production composition is fully ready, startup schedules that exact
  ordered set and attaches the existing terminal callback to each task.
- The existing bounded scheduler limit remains authoritative. More persisted
  queued runs than `MAX_SCHEDULED_TASKS` causes a closed storage-unavailable
  startup rather than silently abandoning a run.
- No public route, DTO, run status, error code, or database schema changed.

## Tests and interrupted exploratory attempt

The focused test set passed: 3 passed in 3.27 seconds. It proves queued FIFO
enumeration, production startup scheduling in that order, and the existing
running/queued/terminal recovery split with fixed interruption code.

A real 62-pair exploratory run was initially started before the parent split
the work into a product-fix commit and a later real-run batch. The process was
terminated at the requested boundary. A subsequent explicit recovery check
produced this minimized state:

- run ID `583f0ef7-8bd9-48f9-b9cd-157564ca4103`;
- recovered running count 1;
- final status `interrupted`, progress 48/62;
- `failure_code=internal_error`;
- queued count 0 and report count 0.

This interrupted local run is not acceptance evidence and no result/report was
used. Its ignored SQLite database is retained only as local diagnostic state.
The complete real 62-pair run must be performed once from a fresh database
after this fix is committed.

## Files

- `src/dataguard/storage/repository.py`
- `src/dataguard/production.py`
- `tests/unit/test_run_report_storage.py`
- `tests/unit/test_production.py`
- `docs/development/DEV_PHASE4_RECOVERY_FIX_2026-08-11.md`

`git diff --check` and final focused regression are recorded at handoff. This is
developer evidence only, not independent testing or architecture acceptance.

## Startup publication correction

Focused review found that the first recovery implementation published runtime
references and `_started=True` before scheduling each recovered queued run. A
schedule or callback-registration exception could therefore close the client/
repository while leaving an already-created task and stale published references.

Startup failure handling now first shuts down the constructed scheduler (which
cancels and joins any owned tasks), clears the bounded run-metrics state, resets
all published service/dependency references and readiness flags to the original
not-started state, and only then closes the Ollama client and repository. Cleanup
continues even if scheduler shutdown itself fails. Parameterized fault tests
cover first-schedule failure, failure after one task was accepted, and callback
registration failure; all require one scheduler shutdown, content-free error,
and completely cleared runtime state.

The corrected focused recovery suite passed: 6 passed in 7.64 seconds. It
includes FIFO enumeration/rescheduling, the locked running/queued recovery split,
and all three publication fault points. `git diff --check` passed at handoff.
