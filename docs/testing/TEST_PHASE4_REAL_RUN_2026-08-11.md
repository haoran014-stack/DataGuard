# Phase 4 complete real-run independent acceptance

- Date: 2026-08-11 (Asia/Shanghai)
- Candidate: `main@bdf30e13b726237e21205b22f83b2c0f29af5f69`
- Development record: `docs/development/DEV_PHASE4_REAL_RUN_2026-08-11.md`
- Retained ignored database: `artifacts/phase4-real-complete-20260811.sqlite3`
- Run ID: `94e82e98-88ff-43ca-a98f-768d6bb347ba`
- Independent method: read-only database/repository/API reconstruction; no evaluation submission and no repeated 124 model calls
- Result: **PASS for original-roadmap Phase 4**
- Phase 6 / portfolio result: **NOT PASSED and NOT ACCEPTED**

## Acceptance boundary

This report accepts the Phase 4 paired-evaluation runner and sanitized report
gate only. It verifies one already completed real Ollama exploratory run, its
persisted report, public read endpoints, minimized audit and the previously
accepted queued/running recovery behavior. It does not accept PostgreSQL,
Docker, strict evidence profile, portfolio eligibility, Phase 5, Phase 6 or V1
evidence.

No evaluation run was created or resumed during independent testing. The
retained database was opened through read-only repository operations and a
SQLite `mode=ro` connection. The repository report validator was installed in
test-process memory instead of invoking schema preparation, so the database was
not migrated or rewritten. Its retained timestamp remained
`2026-08-11T10:30:50Z`.

No raw question, reply, document body, prompt, Canary literal or protected
fragment is reproduced in this report or command evidence.

## Final Phase 4 decision

The persisted run is a complete 62-scenario, 124-mode real-model exploratory
execution with zero failed and zero indeterminate mode results. All scenario
results passed the current Draft 2020-12 report schema and semantic validator;
the canonical report digest, API JSON, deterministic HTML and 124 minimized
mode-audit records were independently rebound.

The report's Guarded authorized-QA pass rate is only 13/30 =
0.43333333333333335 (43.33%). This is an honest exploratory outcome. It does
not invalidate the Phase 4 requirement to execute and report all scenarios,
but it fails the later locked 0.80 quality gate. No parameter, model, fixture,
policy, result or report was changed to improve it. Accordingly:

- `overall_passed=false` is correct;
- `strict_manifest_passed=false` is correct for exploratory SQLite;
- `portfolio_eligible=false` is correct;
- Phase 6 and V1 evidence remain unaccepted.

## Run, report and canonical binding

| Fact | Independently observed |
|---|---|
| Run status | `completed` |
| Progress | 62 / 62 |
| Failure code | null |
| Scenario results | 62 |
| Mode results | 124 |
| Failed mode results | 0 |
| Indeterminate mode results | 0 |
| Report ID | `31f9ebc6-63ed-4e4e-bc36-af3fc3e5d5ea` |
| Canonical report bytes | 236,846 |
| Canonical report SHA-256 | `116845902541087bb422073dbaa4159072f6217cf2140cf2faaaed6778f2c67e` |
| Comparability key | `03dc183a0539cb31a5edccdef359e4bbf2fb338e596ae041a299e239000774d5` |
| Comparability gate | true |
| Strict-manifest gate | false |
| Overall gate | false |
| Portfolio eligible | false |

The stored canonical bytes were parsed, validated by `ReportContract`, checked
again by `validate_report_semantics`, serialized with the locked canonical JSON
algorithm, and freshly hashed. Semantic issue count was 0 and all byte/digest/
run/report bindings matched.

## Fixed scenario distribution

| Family | Count | Language split |
|---|---:|---|
| Authorized QA | 30 | fixed fixture distribution |
| Direct prompt injection | 8 | 4 en / 4 zh |
| Indirect document injection | 8 | 4 en / 4 zh |
| Cross-role retrieval | 8 | 4 en / 4 zh |
| System-prompt inducement | 8 | 4 en / 4 zh |

Outcomes across 124 mode results were 103 answered and 21 blocked. Judgments
were 25 attack succeeded, 39 attack prevented, 24 authorized-QA pass and 36
authorized-QA fail. No scenario or mode result was omitted.

## Baseline and Guarded metrics

| Metric | Baseline | Guarded |
|---|---:|---:|
| Attack attempts | 32 | 32 |
| Attack successes | 25 | 0 |
| Attack success rate | 0.78125 | 0.0 |
| Attack deliveries | 24 / 32 | 27 / 32 |
| Attack delivery rate | 0.75 | 0.84375 |
| Cross-role retrieval authorization violations | 8 / 8 | 0 / 8 |
| Cross-role violation rate | 1.0 | 0.0 |
| Final leaks | reported by mode detail | 0 |
| Unauthorized context documents | reported by mode detail | 0 |

Baseline successes by family:

- direct prompt injection: 8/8;
- indirect document injection: 1/8;
- cross-role retrieval: 8/8;
- system-prompt inducement: 8/8.

All four baseline family gates therefore have at least one success and total
Baseline ASR exceeds the 0.20 evidence threshold. Guarded ASR, final leaks and
unauthorized context are all zero.

The 25 blocked Baseline attacks are attributed mutually exclusively to:

- role filter: 1;
- prompt isolation: 5;
- output gate: 19.

Guarded authorized-QA pass rate is 13/30 = 43.33%, below 80%. Guarded false
rejection rate is 0/30. These values are preserved exactly as generated.

## JSON, HTML and public API consistency

The independent test constructed the current six-route API with read-only
services backed by the retained repository and called the public read routes.

| API evidence | Result |
|---|---|
| `GET /v1/evaluation-runs/{run_id}` | HTTP 200; completed 62/62 |
| `GET /v1/reports/{run_id}?format=json` | HTTP 200; 236,846 bytes; exactly equal to stored canonical bytes |
| API JSON SHA-256 | `116845902541087bb422073dbaa4159072f6217cf2140cf2faaaed6778f2c67e` |
| `GET /v1/reports/{run_id}?format=html` | HTTP 200; exactly equal to deterministic rendering of the same validated report |
| HTML bytes | 519,108 |
| HTML SHA-256 | `7296907825582ea92d1cbbd7af25ac0bca0143b9dba2f92c4891b18b5489b124` |
| `GET /v1/audit-events?run_id=...&limit=200` | HTTP 200; 126 items |

HTML is not a second metric source: it is a deterministic escaped rendering of
the already validated mapping. Exact equality to `render_report_html()` proves
the JSON and HTML facts, denominators, environment and comparability data are
derived from the same report.

## Audit completeness and report binding

| Audit event type | Count |
|---|---:|
| `output_detection_completed` | 124 |
| `run_created` | 1 |
| `run_state_changed` | 1 |
| Total | 126 |

The 124 output events comprise 103 answered and 21 blocked, exactly matching
the report outcome totals. Independent binding constructed unique trace maps
from every report Baseline/Guarded result and every output audit event:

- trace sets were exactly equal and contained 124 entries;
- each event mode/outcome matched its report mode result;
- subject and resolved role matched;
- ordered retrieval evidence matched;
- authorization denials matched;
- minimized detections matched.

The audit endpoint order remains the public `(occurred_at, event_id)` order and
was not misinterpreted as a second execution-sequence field.

## Raw and marker absence

The ignored database contains 6 exact tables and 49 columns. A read-only schema
inspection found no column capable of holding raw question, reply, prompt,
context, document body or generic `raw_*` content. Minimized fields such as
`included_in_context`, Canary match count and protected-fragment match count are
bounded decisions/counts, not raw content.

Exact UTF-8 byte scans of the complete 622,592-byte SQLite file produced zero
hits in every known prohibited category:

| Prohibited category | Fixture/resource probes | Hits |
|---|---:|---:|
| Scenario questions | 62 | 0 |
| Complete document bodies | 30 | 0 |
| Document Canary literals | 30 | 0 |
| Protected-fragment literals | 30 | 0 |
| Complete system-prompt content | 1 | 0 |
| System marker | 1 | 0 |

Arbitrary model replies were intentionally not retained as an independent
reference corpus, so they cannot be value-compared after the fact. Their
absence is instead supported by the exact closed database schema, the 124
hydrated minimized audit objects, report schema closure, and the implementation
contract that never accepts a reply field in persistence. This limitation is
stated rather than fabricating a raw-reply comparison.

The retained database itself has SHA-256
`09995657bd82ee080ea5559552f99ef0d004a3f3d4dfc1c1710654f313d843e3`.

## Queued/running recovery gate

Phase 4 restart behavior is combined from the already accepted recovery fix at
this candidate:

- queued runs enumerate and reschedule in deterministic `(created_at, run_id)`
  FIFO order;
- pre-restart running runs recover atomically to interrupted with fixed
  `internal_error` and no report;
- process-local capacity is 64 and oversized persisted queues fail closed;
- first/middle schedule and callback-publication failures shut down owned tasks
  and roll runtime state back to not-started.

Those boundaries were independently accepted in
`docs/testing/TEST_PHASE4_RECOVERY_FIX_2026-08-11.md` and are present in
`bdf30e1` (`fix: recover queued evaluations safely`). The complete real run and
the recovery fix together satisfy the original-roadmap Phase 4 gate.

## Independent command record

| Check | Exit/result |
|---|---|
| Git HEAD/branch/status | `bdf30e1...`; `main`; only developer real-run record untracked before this report |
| DB ignored-state check | ignored by `artifacts/`; 622,592 bytes |
| Read-only repository/report/API reconstruction | exit 0 |
| Draft 2020-12 schema + semantic validation | 0 issues |
| Canonical recompute/hash/API JSON equality | exact |
| Deterministic HTML equality | exact |
| 124 report-to-audit trace/detail bindings | exact |
| Category-specific privacy byte scan | all categories 0 hits |
| Read-only SQLite schema scan | 6 tables, 49 columns, 0 forbidden raw columns |

The first read-only attempt called `get_report()` without the in-memory report
validator normally installed during startup and correctly failed with the
bounded storage error. The independent test then loaded the current validator
directly into the repository instance rather than calling `prepare_schema()`,
preserving strict read-only handling. A separate initial schema heuristic was
also narrowed because it incorrectly classified allowed minimized count/boolean
columns as raw content; the final exact-column and byte checks are the evidence
used for acceptance.

## Defects and limitations

| Severity | Count | Detail |
|---|---:|---|
| Blocking | 0 | None |
| High | 0 | None |
| Medium | 0 | None |
| Low | 0 | None |
| Quality gate not met | 1 | Guarded authorized-QA pass rate 43.33% is below the later 80% Phase 6 gate |

This low QA result must remain visible. It is not authorized to trigger tuning
or report rewriting in a Phase 4 acceptance batch.

## Final decision

**PASS for original-roadmap Phase 4 at
`bdf30e13b726237e21205b22f83b2c0f29af5f69`.**

The complete real exploratory execution, sanitized paired report/API evidence
and previously accepted queued/running recovery semantics satisfy Phase 4.
`overall_passed=false`, `strict_manifest_passed=false` and
`portfolio_eligible=false` remain authoritative. Phase 5, Phase 6 and V1
evidence are not accepted.
