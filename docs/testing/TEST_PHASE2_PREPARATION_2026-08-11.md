# Phase 2 preparation documentation acceptance

- Date: 2026-08-11 (Asia/Shanghai)
- Candidate baseline: `main@230aac98f1dc7a825825ea4977cd07acd28600ad`
- Batch under test:
  - `docs/architecture/SEVEN_STAGE_ROADMAP.md`
  - `docs/development/DEV_PHASE2_2026-08-11.md`
  - `docs/testing/PHASE2_REAL_OLLAMA_ACCEPTANCE.md`
- Test scope: documentation consistency, current CLI/config/production command feasibility, Phase 2 boundary and safety only
- Product changes: none
- Result: **PASS for Phase 2 preparation documentation**, with the provenance limitation recorded below
- Real Ollama acceptance: **NOT RUN**

## Acceptance summary

The runbook's exploratory sequence is compatible with the current product:

```text
validate -> build-index -> verify-artifacts -> dataguard.server
```

For `profile=exploratory` and `storage_backend=sqlite`, neither
`generate-manifest` nor `DATAGUARD_EXPERIMENT_MANIFEST_PATH` is required.
`verify-artifacts` always probes Ollama and validates the persisted vector index,
but only enters the manifest load/semantic-validation branch when the profile is
`evidence`. Production startup likewise synthesizes an in-memory manifest from
the actual probed/index/resource facts for exploratory operation. The stricter
sequence below is correctly reserved for evidence profile:

```text
build-index -> generate-manifest -> verify-artifacts -> server
```

with PostgreSQL and an explicit
`DATAGUARD_EXPERIMENT_MANIFEST_PATH=artifacts/runtime/experiment-manifest.v1.json`.

No documentation or command defect was found.

## Roadmap and three-document consistency

| Check | Evidence | Result |
|---|---|---|
| Seven-stage structure | Headings enumerate Phase 0 through Phase 6 exactly once and in order | PASS |
| Authoritative numbering | Wrapper explicitly makes the seven-stage numbering authoritative while preserving earlier broader Stage 2 contracts | PASS |
| Phase 2 scope | Ollama, 30-document vector index, deterministic top-4 retrieval and deliberately unguarded Baseline RAG | PASS |
| Development gap table | Implemented items and three real-run gaps match the Phase 2 roadmap acceptance conditions | PASS |
| Runbook boundary | Explicitly excludes Guarded acceptance, paired evaluation, PostgreSQL, Docker and V1 evidence | PASS |
| Files-changed declaration | The three declared Markdown files are the three batch files present in the worktree before this report | PASS |
| Attachment equality | Architecture independently normalized the user attachment to LF with one final LF and compared it to the roadmap body after `---\n\n`: exact equality | PASS (architecture-provided source evidence) |

The original attachment was not present as a separate file in this test agent's
workspace/context, so this agent did not directly read it. The architect
provided independent source evidence: after CRLF/CR-to-LF normalization and one
final LF, the attachment is 5,942 characters, 10,905 UTF-8 bytes and has SHA-256
`e7592e64f8b98a820d596e2b630f5acfd33cedf258555e3494072d795b9b4739`;
the roadmap body after `---\n\n` compared exactly equal. This test agent
independently recomputed the repository body as 5,942 characters, 10,905 bytes
and the same SHA-256. Attachment consistency is therefore accepted using the
architect-provided source comparison while preserving source attribution.

## CLI/config/production feasibility

| Runbook operation | Current behavior checked | Result |
|---|---|---|
| `python -m dataguard validate` | Unified parser exposes the command; actual run returned the stable Stage 1 JSON with 6 identities, 30 documents, 62 scenarios and 0 issues | PASS |
| `build-index` | Uses current exploratory settings, probes exact Ollama facts, embeds the accepted corpus, and writes only through the safe vector-index store; overwrite remains explicit | PASS, static/unit; real Ollama NOT RUN |
| `verify-artifacts` | Probes Ollama and validates index binding; manifest is conditional on `profile=evidence` | PASS, static/unit; local no-Ollama invocation failed closed as expected |
| `dataguard.server` | Factory reads the same closed environment, creates exactly six routes without startup I/O, and binds loopback by default | PASS |
| exploratory manifest | `profile=exploratory`, SQLite and no manifest path are valid; startup derives current facts rather than reading an evidence artifact | PASS |
| evidence manifest | CLI generation requires evidence + PostgreSQL; verify/startup require the explicit path and fail closed on mismatch | PASS; outside Phase 2 runbook scope |

The exact runbook environment independently parsed as:

```text
profile=exploratory
storage_backend=sqlite
experiment_manifest_path=None
runtime_state_dir=artifacts/runtime
database_dsn scheme=sqlite+pysqlite
ollama_base_url=http://127.0.0.1:11434
```

The direct `verify-artifacts` attempt on this host returned exit 1 and only the
bounded JSON code `artifact_preparation_failed`, because a real local Ollama and
prepared bound index were unavailable. This is the expected prerequisite
failure and does not contradict command feasibility.

## Phase 2 safety and scope boundary

- The procedure never installs, starts or pulls Ollama and stops when either
  exact tag is absent.
- Only loopback Ollama and loopback API endpoints are used.
- The query names a synthetic fixture document and does not embed a Canary or
  protected literal in the command.
- Evidence instructions prohibit recording raw model replies, document bodies,
  Canary literals or protected fragments. Only trace IDs, document IDs,
  detection type and opaque evidence ID are retained.
- Baseline's intentional lack of authorization filtering is limited to the
  committed synthetic corpus and is clearly identified as a controlled Phase 2
  weakness.
- The runbook requires an actual observed Baseline detection while preserving
  `outcome=answered`; if the fixed model does not reproduce it, acceptance must
  fail rather than tune Guarded behavior or claim success.
- The unavailable-Ollama check requires a catalogued 503 and forbids a
  simulator response.
- Later-phase minimized audit is used only to observe retrieval order and the
  controlled Baseline hit. The runbook does not accept Guarded, evaluation,
  PostgreSQL, Docker, or V1 evidence.
- Persisting the index is a safe restart/binding extension over the roadmap's
  in-process wording; it does not change the Phase 2 retrieval semantics.

## Commands and results

| Command/check | Exit/result |
|---|---|
| `git status --short` before testing | Three untracked batch documents only |
| `git log -1 --oneline` | `230aac9 docs: accept stage2 implementation` |
| `python -m pytest -q tests/unit/test_cli_server.py --basetemp E:\ai-security-cache\dg-phase2-doc-acceptance` | exit 0; 5 passed in 4.63 s |
| `python -m dataguard validate` | exit 0; 0 issues, 6/30/62 fixed counts |
| `python -m dataguard --help` | exit 0; expected four unified subcommands |
| `python -m dataguard verify-artifacts` without Ollama/index prerequisite | exit 1; bounded `artifact_preparation_failed` |
| Direct `RuntimeSettings.from_env` with runbook settings | accepted; exploratory/SQLite/no manifest path |
| Roadmap structural/digest check | Phase 0-6 exact; body including one final LF is 5,942 characters, 10,905 UTF-8 bytes, SHA-256 `e7592e64...b4739` |
| UTF-8/BOM/LF/final-LF/trailing-whitespace check on three documents | all UTF-8, no BOM, LF only, final LF present, 0 trailing whitespace |
| Markdown local-link check | roadmap link exists |
| `git diff --check` | exit 0 |

The developer record's `git diff --check` result alone cannot inspect untracked
file content. The independent byte/line scan above directly checked all three
files and found no formatting defect.

## Defects and limitations

| Severity | Count | Detail |
|---|---:|---|
| Blocking | 0 | None |
| High | 0 | None |
| Medium | 0 | None |
| Low | 0 | None |
| Source attribution | 1 | This test agent did not directly read the user attachment; exact normalized equality and attachment digest were independently supplied by the architect and matched this agent's repository-body digest |

## Final decision and next context

**PASS for the documentation-only Phase 2 preparation batch.** This does not
accept Phase 2 itself. Phase 2 remains pending an already-running local Ollama
with both exact tags, successful build/verify/server execution, two stable
Baseline retrieval observations, at least one controlled observe-only leak
detection, and the explicit dependency-down 503 check. The resulting minimized
record must then be independently verified and architect-reviewed.
