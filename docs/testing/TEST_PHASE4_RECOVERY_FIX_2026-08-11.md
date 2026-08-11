# Phase 4 queued-recovery fix independent acceptance

- Date: 2026-08-11 (Asia/Shanghai)
- Baseline: `main@47959effb01059731611ec10d0afb18dd95bc46c`
- Scope: original-roadmap Phase 4 queued/running restart semantics only
- Product changes reviewed:
  - `src/dataguard/storage/repository.py`
  - `src/dataguard/production.py`
- Test changes reviewed:
  - `tests/unit/test_run_report_storage.py`
  - `tests/unit/test_production.py`
- Developer record: `docs/development/DEV_PHASE4_RECOVERY_FIX_2026-08-11.md`
- Real 62-pair / 124-mode run: **NOT RUN by instruction**
- Final result on current worktree: **PASS**

## Outcome

The current worktree closes the queued-recovery gap without changing any public
route, DTO, status, error code or database schema:

- persisted `queued` runs are listed in deterministic
  `(created_at, run_id)` FIFO order;
- pre-restart `running` recovery remains atomically mapped to `interrupted` with
  fixed `failure_code=internal_error`, while queued and terminal states remain
  unchanged;
- at most 64 persisted queued tasks are admitted to the process-local
  scheduler; 65 or more fail startup closed with `storage_unavailable`;
- production startup schedules the ordered queued set and binds each existing
  terminal callback to its own run ID;
- any first-schedule, middle-schedule or callback-registration failure shuts
  down the scheduler, clears run metrics, removes all published dependency and
  service references, restores not-started readiness state, and closes client/
  repository dependencies;
- a failed startup is retryable as a fresh startup because `_started=False` and
  `_closed` remains at its pre-start value.

No open blocking, high, medium or low defect remains in this limited fix.

## Defect discovery and closure

### DG-P4-REC-001 — startup publication failure cleanup

- Initial severity: **Medium**
- Initial status: confirmed on the first worktree snapshot
- Final status: **Closed and independently reverified**

The first implementation published `_repository`, `_client`, `_scheduler` and
other runtime references and set `_started=True` before iterating recovered
queued runs. If `schedule()` or `add_done_callback()` raised, the outer handler
closed only the local client/repository. It did not shut down the scheduler,
cancel an already accepted task, clear published references, or reset
`_started`. An independent injected first-schedule failure reproduced:

```text
started_after_failed_startup=true
scheduler_shutdown_calls=0
repository_reference_retained=true
client_reference_retained=true
```

This was reported before any product modification by the test agent. The
shared worktree was then corrected by development. On the corrected candidate,
the same independent probe produced:

```text
started_after_failed_startup=false
scheduler_shutdown_calls=1
repository_reference_retained=false
client_reference_retained=false
```

The committed product test addition separately covers first-schedule failure,
failure after one task has been accepted, and callback-registration failure.
Each asserts minimized errors, one scheduler shutdown and complete runtime
reference/readiness rollback. The defect is therefore closed for this
acceptance.

## Requirement evidence

| Requirement | Independent evidence | Result |
|---|---|---|
| FIFO `(created_at, run_id)` | Repository test creates later, then two equal-time UUID runs; only queued results return in timestamp/UUID order | PASS |
| Only queued are rescheduled | A transitioned running record is excluded from `list_queued_runs()` | PASS |
| Running recovery unchanged | Existing recovery test verifies only running becomes interrupted with fixed internal error; queued/terminal remain unchanged | PASS |
| Production startup order | Injected scheduler records persisted run IDs in repository FIFO order | PASS |
| Callback run binding | Lambda uses a default `run_id=queued_run.run_id`, avoiding loop-variable late binding | PASS |
| Capacity exactly 64 | Existing scheduler boundary test preserves `MAX_SCHEDULED_TASKS == 64` and rejects the next admission | PASS |
| Persisted queue >64 | Independent 65-run startup probe returns `storage_unavailable`, `_started=False`, and publishes no repository/scheduler references | PASS |
| First schedule failure | Corrected product parameterized test and independent probe both verify shutdown/reset | PASS |
| Middle schedule failure | Corrected product test verifies the already accepted task is owned and cleaned through scheduler shutdown | PASS |
| Callback failure | Corrected product test verifies scheduler shutdown and full state rollback after task creation | PASS |
| Metrics/dependency cleanup | Startup exception path clears run metrics and resets all service/dependency fields before closing client/repository | PASS |
| No public/schema drift | Diff adds only repository protocol/method and startup composition behavior; no route, DTO, enum, code or DDL change | PASS |

## Commands and results

| Command/check | Exit/result |
|---|---|
| Initial `git status --short` | only two product files, two test files and the developer record were changed |
| First focused selection | exit 0; 4 passed in 3.95 s (FIFO, running recovery, startup FIFO, scheduler capacity) |
| Initial independent injected failure probe | exit 0 as a defect reproducer; stale started state and missing scheduler cleanup confirmed |
| Corrected focused selection | exit 0; 7 passed in 7.65 s, including three publication-fault parameters |
| Corrected independent cleanup/capacity probe | exit 0; 2 passed in 4.84 s |
| `git diff --check` | exit 0 |

The independent corrected probe facts were:

```text
schedule failure:
  started=false
  scheduler shutdown calls=1
  repository/client references retained=false

65 persisted queued runs:
  code=storage_unavailable
  started=false
  repository/scheduler references published=false
```

No real model evaluation, report generation or 124-mode execution occurred.
All tests used bounded unit fixtures and temporary SQLite state beneath the
external test basetemp.

## Code review notes

### Repository FIFO

`list_queued_runs()` holds the existing repository lock, requires an open
repository, revalidates runtime storage and schema, filters exactly
`status=queued`, orders in SQL by `created_at` then `run_id`, hydrates closed
`EvaluationRun` models, and minimizes all unexpected failures to
`StorageError`. It does not mutate persisted state.

### Recovery ordering

Startup performs `recover_interrupted_runs()` before the index/model readiness
composition and before `list_queued_runs()`. Consequently a pre-restart running
record is converted to interrupted before enumeration and cannot be scheduled
as queued. Persisted queued records remain queued until the existing runner
starts them one at a time through the scheduler semaphore.

### Capacity and publication

The repository result is prechecked against the scheduler's authoritative
constant before runtime fields are published. Exactly 64 can be scheduled; a
larger persisted set raises the fixed storage-unavailable startup error. The
same scheduler still enforces its task-plus-reservation bound internally.

Runtime references must be published before created tasks execute because the
terminal callback and runner use the composed services. The corrected exception
path makes this temporary publication transactional from the caller's
perspective: scheduler-owned tasks are cancelled/joined first, metrics are
cleared, every published field is reset, and dependencies are closed. Callback
closures bind each queued run ID at registration time.

## Defects and residuals

| Severity | Open | Closed in batch | Detail |
|---|---:|---:|---|
| Blocking | 0 | 0 | None |
| High | 0 | 0 | None |
| Medium | 0 | 1 | DG-P4-REC-001 startup failure cleanup, independently reverified closed |
| Low | 0 | 0 | None |

Residual scope remains unchanged: the scheduler is process-local, concurrency
is one, capacity is 64, and recovery does not backfill historical metrics. The
previously interrupted exploratory diagnostic run is not acceptance evidence.
A fresh complete Phase 4 real run remains a separate later batch.

## Final decision

**PASS for the current Phase 4 queued-recovery minimum fix, including the
follow-up publication-failure correction.** This report is bound to baseline
`47959effb01059731611ec10d0afb18dd95bc46c` plus the reviewed worktree diff.

This is not Phase 4 real-run/report acceptance and does not accept any Phase 5,
Phase 6 or V1 evidence gate.
