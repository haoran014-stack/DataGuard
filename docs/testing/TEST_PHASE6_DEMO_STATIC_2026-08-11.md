# Phase 6 demo static and unit acceptance

- Date: 2026-08-11 (Asia/Shanghai)
- Candidate: `main@fd7e27cdf8b74ef4e20acb85bba275c10fa60877`
- Scope: static delivery review plus deterministic unit/full-pytest execution
- External runtime: **NOT RUN by instruction** (no Docker, API, PostgreSQL or Ollama invocation)
- Result: **PASS after one Medium README consistency defect was corrected and rechecked**

## Acceptance boundary

This pass reviews the Phase 6 demonstration implementation and documentation
claims only. It does not execute the demonstration, create an evidence run,
contact the API, start Compose, access PostgreSQL or invoke Ollama. It therefore
does not accept Phase 6 real evidence or V1 release gates.

The test agent modified no product, script, fixture, contract, architecture,
README or development file; its only repository change is this report. During
testing, development independently corrected `README.md` and added its scoped
development record; those concurrent changes were reviewed but not authored by
the test agent.

## Requirement matrix

| Requirement | Evidence | Result |
|---|---|---|
| Roadmap five demonstration cases | `demo_client.py` performs Baseline cross-role, Guarded role filter, Guarded indirect injection, Guarded Canary block and authorized confidential reviewer QA | PASS |
| Complete evidence workflow | creates a distinct `profile=evidence` 62-scenario run, polls to `completed`, requires `completed_scenarios=62`, retrieves JSON/HTML and then run-filtered audit | PASS statically; real execution NOT RUN |
| Dynamic fixtures | loads the typed fixture bundle at runtime, selects four fixed scenario IDs, and validates family/role/document semantics in unit tests | PASS |
| No copied raw question | source contains no duplicated question literal; accepted typed scenario questions flow directly into the request payload | PASS |
| Reply handling | `_chat` removes `reply`, retains only UUID trace/outcome in a `repr=False` fact, explicitly clears it, and never prints, writes or returns it to the caller | PASS |
| Minimal errors | internal failures use fixed content-free `DemoFailure` messages; `main` catches all exceptions and emits only `DEMO STATUS failed` | PASS |
| Loopback URL and port | only `http://127.0.0.1:<1..65535>` with root path/no userinfo/query/fragment is accepted; PowerShell `ApiPort` is range-checked and feeds both Compose and client URI | PASS |
| Report paths | fixed to existing `<root>/artifacts/report.json` and `report.html`, with resolved containment and direct-parent checks | PASS |
| Evidence-ready health | requires healthy status, `evidence_readiness=true`, PostgreSQL up/backend and Ollama up before any chat | PASS |
| Baseline evidence | requires unauthorized retrieved document included in context plus an observed detection | PASS |
| Guarded role evidence | requires authorization denials and permits only authorized included documents | PASS |
| Indirect evidence | target must be included and authorized; blocked requires blocking violation, answered requires no violation | PASS |
| Canary evidence | requires blocked outcome and document/system Canary violation with blocked action | PASS |
| Reviewer evidence | fixed authorized-QA reviewer scenario must answer with an authorized target document in context | PASS |
| Artifact preflight | validates fixtures; handles both-artifact reuse, both-absent generation, explicit overwrite, and fails on one-artifact state; always verifies artifacts before Compose | PASS |
| Destructive safeguards | never pulls models; cleanup uses `docker compose down` without `-v`; volume deletion requires separate explicit operator choice | PASS |
| README demo instructions | correctly describes five cases, complete evaluation, JSON/HTML/audit, no reply output, fixed timeouts and alternate `ApiPort` | PASS |
| README current status | now distinguishes accepted Phase 2–5 real integration from the pending rebuilt Phase 6 evidence run/V1 release | PASS after correction |

The report endpoint itself validates stored canonical reports before serving
them. The demo additionally checks the returned mapping is a dictionary bound
to the requested run and that both representations are non-empty, writes the
two sanitized representations to fixed artifact paths, and prints only the
JSON SHA-256. The run audit request uses a fixed limit of 200, sufficient for
the expected 126 events, and requires a non-empty item list. This meets the
roadmap demonstration requirement to query audit and report; it is not treated
as independent real evidence validation.

## Automated results

| Command | Exit | Result |
|---|---:|---|
| `.venv/Scripts/python -m pytest tests/unit/test_demo_client.py tests/unit/test_delivery_files.py --basetemp E:/ai-security-cache/dg-phase6-targeted -q` | 0 | 38 passed in 0.63s |
| `.venv/Scripts/python -m pytest --basetemp E:/ai-security-cache/dg-phase6-full-fd7e27c -q` | 0 | 763 passed in 101.10s |
| `.venv/Scripts/python -m pytest tests/unit/test_delivery_files.py --basetemp E:/ai-security-cache/dg-phase6-readme-recheck -q` | 0 | post-fix 6 passed in 0.06s |

The full suite used a new basetemp outside the repository. No existing test
result, Docker/API/Ollama state or prior runtime database was used as a
substitute for these deterministic checks.

## Defect

### P6-DOC-01 — README falsely said real dependencies and integrations were not run

- Severity: **Medium**
- Status: closed in the candidate worktree and independently rechecked
- Files: `README.md` lines 6–10 and the `Limitations` statement around lines
  286–289

The initially tested README said the current development host lacked Docker and Ollama and that
real Compose, PostgreSQL, model and evidence verification are all `NOT RUN`.
That is directly inconsistent with committed repository evidence:

- `TEST_PHASE2_REAL_OLLAMA_2026-08-11.md` accepts the real Ollama gate;
- `TEST_PHASE3_REAL_GUARDED_2026-08-11.md` accepts real guarded chat cases;
- `TEST_PHASE4_REAL_RUN_2026-08-11.md` accepts the complete real exploratory run;
- `TEST_PHASE5_DOCKER_POSTGRES_2026-08-11.md` accepts real Docker/PostgreSQL,
  host Ollama connectivity, parity and interruption recovery.

This was not merely a missing latest measurement: it made a false public claim
about which integration work occurred. It conflicts with the Phase 6 goal of
complete, non-overstated and traceable documentation. The README may continue
to say that no qualifying Phase 6 evidence/V1 report exists and that Phase 6
gates remain unaccepted; it had to distinguish that valid statement from the
already executed Phase 2–5 real integration evidence.

During this independent run, development changed only `README.md` and added
`docs/development/DEV_PHASE6_README_STATUS_2026-08-11.md`. Independent diff
review confirmed the replacement text now links the Phase 5 test and
architecture acceptance, states that real local Ollama/SQLite/PostgreSQL/Docker
acceptance passed only for the recorded synthetic environment, and separately
states that the post-QA-correction rebuilt-image formal evidence run and V1
release remain incomplete/unaccepted. This closes the contradiction without
inventing a Phase 6 result. `test_delivery_files.py` was rerun after the change:
6 passed in 0.06s.

No raw model output or security marker is involved in this defect.

## Residual test boundary

- Static and unit acceptance cannot prove the five chats succeed against the
  current real models or that a new evidence run reaches all release gates.
- The demo writes API-served sanitized report bytes; this pass did not inspect
  a newly produced report because external runtime execution was forbidden.
- Passing 763 deterministic tests and closing the README defect do not
  constitute Phase 6/V1 evidence.

## Conclusion

The Phase 6 demo implementation passes the requested static safety, coverage
and deterministic regression checks. The only Medium documentation defect was
found, corrected by development, and independently closed in the same
acceptance run. The current candidate worktree is therefore **PASS for Phase 6
demo static/documentation acceptance**. Phase 6 real evidence and V1 release
remain **NOT RUN / NOT ACCEPTED** in this test scope.
