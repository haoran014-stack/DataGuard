# Phase 5 architecture acceptance

- Date: 2026-08-11 (Asia/Shanghai)
- Accepted candidate: `main@2464fc34513a1d939f001ca1323b74ff2c2fb15e`
- Decision: **PASS for original-roadmap Phase 5**
- Phase 6 / V1 evidence: **NOT AUTHORIZED as passing evidence**

## Accepted boundary

Phase 5 now has real Docker, PostgreSQL and host-Ollama evidence rather than a
unit-only delivery claim. Compose contains exactly the DataGuard API and
PostgreSQL, publishes no PostgreSQL host port, mounts prepared artifacts
read-only, and reaches the separately managed Ollama service through
`host.docker.internal`. The API host port and evaluation profile are explicit
operator inputs with locked defaults of `8000` and `evidence`; this host used
loopback port `18000` and the explicit `exploratory` profile for the required
clean-database comparison without stopping IIS.

The accepted PostgreSQL run `7cb5039d-37c6-4bcd-afaf-868f1daf18b5`
completed all 62 paired scenarios and 124 mode executions with no failed or
indeterminate mode. Its canonical report passes Draft 2020-12, format checking
and the product semantic validator. All locked aggregates exactly match the
accepted Phase 4 SQLite run, apart from the declared storage backend.

## Acceptance evidence

| Gate | Result |
|---|---|
| Compose topology and health | API plus PostgreSQL only; both healthy; PostgreSQL private |
| Real dependencies | Ollama 0.32.8 and both fixed model digests observed by the container |
| PostgreSQL parity | 62/124 shape and every locked metric equal to Phase 4 SQLite |
| Canonical report | 236,853 bytes; SHA-256 `bae3ec1134210b142e8ef7df30072ec249e3e6914e99e597e2df8b68d4189ae1` |
| Audit binding | 126 events; all 124 mode trace IDs rebound exactly |
| Storage/log privacy | six application tables, no raw-content columns, tested sensitive hits zero |
| Dependency failure | database-dependent routes returned 503 while PostgreSQL was stopped |
| Recovery | in-flight probe became `interrupted`; prior completed report retained identical SHA |
| Evidence preflight | retained manifest accepted; one locked-fact drift probe rejected without raw echo |
| Open product defects | zero blocking, high, medium or low findings |

The PostgreSQL volume was never deleted. No simulator, Ollama container or
additional worker was introduced. Full independent evidence is recorded in
[`TEST_PHASE5_DOCKER_POSTGRES_2026-08-11.md`](../testing/TEST_PHASE5_DOCKER_POSTGRES_2026-08-11.md).

## Residuals and next gate

The cached `/health` snapshot does not change during a post-start PostgreSQL
outage, although authoritative database operations correctly fail closed with
503 and restart recovery is explicit. This is an operational observability
limitation, not a Phase 5 correctness failure.

Phase 6 is authorized only for a reviewed quality improvement and a new fixed-
manifest evidence run. The current guarded authorized-QA result remains
13/30 (43.33%), below the mandatory 80% threshold. Baseline ASR is 25/32,
guarded final leaks and unauthorized context documents are zero, false
rejections are zero, and indeterminate results are zero; none of those passing
facts permits the QA gate to be weakened or the exploratory report to be
relabeled as V1 evidence.
