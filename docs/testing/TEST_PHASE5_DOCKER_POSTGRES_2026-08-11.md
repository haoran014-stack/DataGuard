# Phase 5 Docker/PostgreSQL independent acceptance

- Date: 2026-08-11 (Asia/Shanghai)
- Candidate: `main@2464fc34513a1d939f001ca1323b74ff2c2fb15e`
- Candidate parent: `7e8b2bc98ed2c3b250477116791ef02e8d481635`
- API: `http://127.0.0.1:18000`
- Completed PostgreSQL run: `7cb5039d-37c6-4bcd-afaf-868f1daf18b5`
- Fault-probe run: `c19db9dc-2676-483a-a9e6-e37ef3da5dc0`
- Result: **PASS for original-roadmap Phase 5 Docker/PostgreSQL acceptance**
- Phase 6 / V1 evidence: **NOT PASSED and NOT ACCEPTED**

## Boundary and decision

This is an independent, read-only acceptance of the retained real-model
PostgreSQL result plus a bounded destructive-service availability probe. No
124-call evaluation was repeated. The only service mutation was stopping and
starting the exact Compose `postgres` service and restarting the exact `api`
service; no `down`, volume removal or image/fixture/product mutation occurred.

The completed PostgreSQL run is a complete 62-scenario/124-mode result. Its
canonical report passes Draft 2020-12 plus the product semantic validator, its
API JSON and HTML are bound to the same report, and all locked aggregates are
exactly equal to the accepted Phase 4 SQLite run apart from the declared
storage backend. PostgreSQL interruption fails closed, and startup recovery
changes an in-flight run to `interrupted`; the retained completed report stays
byte-identical after recovery. Database rows and both container logs contain
no exact fixture/resource sensitive values tested below.

No raw question, reply, document body, prompt, Canary literal, protected
fragment, database credential or model response is reproduced in this report.

## Compose and real dependency evidence

`docker compose ps --format json` and container inspection established:

| Property | Independent observation |
|---|---|
| Compose services | exactly `api` and `postgres` |
| API | running/healthy; loopback publish `127.0.0.1:18000 -> 8000/tcp` |
| PostgreSQL | `postgres:17.6-bookworm`; running/healthy after recovery |
| PostgreSQL host publication | none (`5432/tcp` is container-only) |
| Persistence | named volume remained attached; it was not deleted |
| API filesystem/security | read-only root, tmpfs runtime paths, artifacts read-only bind, non-root image, dropped capabilities/no-new-privileges per Compose/Dockerfile |
| Ollama | API health reported real Ollama `0.32.8` and the fixed generation/embedding model digests |
| Simulator | no simulator service or success path in Compose; completed report records PostgreSQL and the real fixed model facts |

Before the fault probe, `/health` reported Ollama and PostgreSQL up and
`readiness=true`. Thus the container-to-host Ollama gateway was exercised by
the actual completed evaluation rather than replaced by a simulated service.

## Completed run, contract and canonical binding

| Fact | Independently observed |
|---|---:|
| Run status/progress | completed, 62/62 |
| Scenario results / mode results | 62 / 124 |
| Failed / indeterminate mode results | 0 / 0 |
| Report ID | `f0bd3247-cbe0-415b-bd91-7edcb2b64f83` |
| Canonical/API JSON bytes | 236,853 |
| Canonical/API JSON SHA-256 | `bae3ec1134210b142e8ef7df30072ec249e3e6914e99e597e2df8b68d4189ae1` |
| HTML bytes | 519,115 |
| HTML SHA-256 | `20030ff330797dc8c1def29038d3ff9f9db2fe8c8d9305f9ed826f3009cbd639` |
| Draft 2020-12 + FormatChecker | pass |
| Product report semantic issues | 0 |
| Comparability key | `03dc183a0539cb31a5edccdef359e4bbf2fb338e596ae041a299e239000774d5` |

The API JSON was exact canonical JSON (sorted keys, compact separators,
finite numbers and one final LF). `ReportContract`, Draft 2020-12 with format
checking, and `validate_report_semantics` independently accepted it. The HTML
was exactly the deterministic escaped rendering of that validated mapping.

The fixed distribution was 30 authorized-QA scenarios plus 8 scenarios in
each of direct prompt injection, indirect document injection, cross-role
retrieval and system-prompt inducement. Each attack family was 4 English and
4 Chinese. Outcomes across the 124 mode results were 103 answered and 21
blocked. Judgments were 39 attack prevented, 25 attack succeeded, 24
authorized-QA pass and 36 authorized-QA fail.

## Metrics and Phase 4 SQLite parity

| Metric | Baseline | Guarded |
|---|---:|---:|
| Attack successes / attempts | 25/32 | 0/32 |
| Attack success rate | 0.78125 | 0.0 |
| Attack deliveries | 24/32 | 27/32 |
| Attack delivery rate | 0.75 | 0.84375 |
| Cross-role authorization violations | 8/8 | 0/8 |
| Guarded final leaks | n/a | 0 |
| Guarded unauthorized context documents | n/a | 0 |

Baseline attack successes by family were direct 8/8, indirect 1/8,
cross-role 8/8 and system-prompt inducement 8/8. The 25 blocked Baseline
attacks were attributed to role filter 1, prompt isolation 5 and output gate
19. Guarded authorized-QA pass rate was 13/30 = 0.43333333333333335 and false
rejection rate was 0/30.

An independent read-only comparison with
`artifacts/phase4-real-complete-20260811.sqlite3` found exact equality for:

- 62/124 shape, family/language distribution, outcomes and judgments;
- every summary numerator, denominator and rate;
- prevention-stage counts and every gate value;
- comparability key, with only `sqlite` changing to `postgresql` as intended.

The comparability gate is true. The strict-manifest, overall and portfolio
gates are false because this retained Compose run is exploratory and QA is
43.33%, below the later 80% threshold. This honest Phase 6 miss does not
invalidate the Phase 5 storage/deployment acceptance and must not be promoted
to V1 evidence.

## Audit and minimized persistence

The completed run exposed 126 audit events: 124
`output_detection_completed`, one `run_created`, and one
`run_state_changed`. All 124 report trace IDs were unique and exactly matched
the output-event trace set. Mode, outcome, subject/role, ordered retrieval,
authorization denials and minimized detections were rebound for every result.

Live PostgreSQL schema inspection found exactly six application tables. It
found no column whose name can retain a raw question, reply, prompt,
`context_text`, document body or `raw_*` value. The database contained two
runs and one report after the fault probe; exact sensitive-value substring
checks over all string cells returned:

| Category | Exact hits |
|---|---:|
| 62 scenario questions | 0 |
| 30 complete document contents | 0 |
| 30 Canary literals | 0 |
| 30 protected fragments | 0 |

Container logs were captured in memory and never reproduced. The API log was
0 bytes; the PostgreSQL log was 6,877 bytes / 85 lines. Exact checks in each
log independently returned zero hits for all four categories above and the
system marker. Arbitrary raw replies were not retained as a reference corpus;
their absence is supported by the closed database schema and minimized report
and audit contracts, not by a fabricated post-hoc value comparison.

## Real PostgreSQL interruption and recovery

The independent probe created run
`c19db9dc-2676-483a-a9e6-e37ef3da5dc0` and observed it enter `running`. It
then stopped only the Compose PostgreSQL service. While PostgreSQL was down:

- reading the new run returned authoritative HTTP 503;
- reading the prior completed report returned authoritative HTTP 503;
- no synthetic run/report success was returned.

PostgreSQL was started and polled to healthy, then only the API service was
restarted and polled to healthy. Startup recovery exposed the in-flight run as
`interrupted` over HTTP 200 with no successful report. The prior completed
report again returned HTTP 200, 236,853 bytes, with the exact pre-fault SHA-256
`bae3ec1134210b142e8ef7df30072ec249e3e6914e99e597e2df8b68d4189ae1`.
The named PostgreSQL volume remained attached throughout.

Residual observation: `/health` continued to return its cached startup
`healthy` snapshot during the database outage even though DB-dependent routes
correctly returned 503. This is consistent with the documented no
request-time dependency probing/cached-health design, but operators must treat
it as a runtime observability limitation. It is not a Phase 5 blocking defect
because authoritative operations fail closed and restart recovery is explicit.

## Evidence preflight and drift

The retained manifest SHA-256 is
`8af174dd0b64fbc2d2df05780ae0ed0ea66ab9b50a9aeea091b62769d70069c3`.
The validated vector-index artifact SHA-256 is
`b5add8cd106e5f2124ab81db73fb0b8867114f620ed379ef8310deadf8645dfa`.

With `profile=evidence`, PostgreSQL settings, the explicit manifest path and
the real local Ollama/models, `python -m dataguard verify-artifacts` exited 0
and returned fixed status `ok`. A separate in-memory negative probe changed
one non-sensitive locked manifest fact without modifying the retained file;
`create_evaluation_context` rejected the drift and the probe emitted only a
content-free rejection status. Negative probes: 1; rejected: 1; raw echo: 0.

## Defects and residuals

| ID | Severity | Status | Finding |
|---|---|---|---|
| P5-R1 | residual | open/non-blocking | Cached `/health` remains healthy during a post-start PostgreSQL outage; DB-dependent operations still fail closed with 503. |
| P5-R2 | phase-boundary | open/non-blocking for Phase 5 | Exploratory QA pass rate is 43.33%; Phase 6 quality and V1 evidence remain unaccepted. |

No blocking, high, medium or low product defect was found in this bounded
Phase 5 acceptance.

## Command record

| Command/check | Exit/result |
|---|---|
| Git HEAD/branch/status/parent | exit 0; candidate above; `main`; clean before report |
| Docker client/server version | exit 0; 29.7.2 / 29.7.2 |
| `docker compose ps --format json` + inspect | exit 0; exactly two healthy services; PG no host port |
| API completed-run/report/audit probe | exit 0; 62/124; schema+semantic pass; 126 audits |
| Phase 4 read-only SQLite parity probe | exit 0; all locked aggregates equal |
| `docker compose stop postgres` | exit 0; exact service stopped; volume retained |
| outage run/report reads | HTTP 503 / HTTP 503 |
| `docker compose start postgres`; health poll | exit 0; healthy |
| `docker compose restart api`; health poll | exit 0; healthy |
| recovered fault run / retained report | interrupted / HTTP 200 and unchanged SHA |
| live PostgreSQL schema/value scan | exit 0; 6 tables; forbidden columns 0; sensitive hits 0 |
| API/PostgreSQL in-memory log scan | exit 0; sensitive hits 0 |
| evidence `verify-artifacts` | exit 0; status ok |
| one in-memory manifest drift probe | exit 0; 1/1 rejected; no raw echo |

## Final conclusion

**PASS for Phase 5 Docker/PostgreSQL.** The Compose boundary, real Ollama
connectivity, PostgreSQL persistence, completed-result parity, minimized
audit/storage, outage fail-closed behavior, restart recovery and evidence
preflight/drift rejection satisfy this phase. **Phase 6 and V1 evidence remain
NOT ACCEPTED** because this is an exploratory run and the locked QA quality
gate is not met.
