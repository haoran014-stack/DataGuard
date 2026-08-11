# Phase 6 development record - safe demonstration coverage

## Scope

- Reviewed the five demonstration categories in the seven-stage roadmap and
  implemented a local HTTP driver without changing the product API.
- `scripts/demo.ps1` remains responsible for dependency preflight, fixture and
  artifact validation/preparation, Compose configuration/startup, and the
  validated configurable host port.
- `scripts/demo_client.py` loads committed fixtures dynamically and drives the
  HTTP API using four fixed scenario IDs. No raw question is copied into source.
- No real API, container, database, Ollama model, or evaluation was run in this
  development batch. No commit or push was performed.

## Demonstration evidence

The helper proves each case only from public response state and minimized audit
evidence:

1. Baseline cross-role risk requires at least one unauthorized document included
   in context and at least one violating detection with action `observed`.
2. The same question in guarded mode requires authorization denials and only
   authorized included documents.
3. Guarded indirect-document injection first proves an attack target was
   included in authorized-only context. A `blocked` result requires a violating
   detection with action `blocked`; an `answered` result is also safe when no
   violating detection exists. This avoids treating nondeterministic but safe
   model behavior as a demo failure.
4. Guarded direct/Canary output similarly requires a blocked response plus
   blocked violation evidence.
5. Confidential reviewer QA requires `outcome=answered` and authorized-only
   retrieved context.
6. The evidence run retains a 45-minute deadline, must finish `completed/62`,
   exports the validated report JSON and HTML beneath the existing local
   `artifacts` directory, prints only its run ID and JSON response SHA-256, and
   queries minimized run audit evidence.

The reply field is removed immediately inside the chat helper and is never
printed, logged, returned from the helper, or written to disk. Standard output
contains only fixed step/status lines, the run ID, and report SHA-256.

## Files

- `scripts/demo_client.py`: loopback-only HTTP helper and bounded workflow.
- `scripts/demo.ps1`: replaced embedded HTTP calls with one helper invocation.
- `tests/unit/test_demo_client.py`: fixed-scenario semantics, URL and path bounds.
- `tests/unit/test_delivery_files.py`: static step, timeout, and reply-minimization checks.
- `README.md`: documented the fixture-backed safe demonstration.

## Development-side checks

| Command | Exit | Evidence |
|---|---:|---|
| Initial focused pytest with system temp | nonzero | 18 passed; 2 setup errors because the system pytest temp root denied access. |
| First safe-basetemp retry | nonzero | 19 passed; exposed that a file named `artifacts` was not rejected by the output-path validator. |
| Final focused pytest with repository-safe basetemp | `0` | `20 passed in 0.62s`. |
| Python `py_compile` plus PowerShell parser | `0` | `SCRIPT_PARSE_OK`. |

The output-path defect found by the negative test was fixed by requiring both
the project root and resolved `artifacts` target to be directories before fixed
report paths are returned. This record is development evidence only, not an
integration run or independent acceptance.

### Architecture correction: indirect-injection outcome

The initial helper required the indirect case to be blocked. Architecture
review clarified that the roadmap requires coverage of a delivered indirect
document attack, while a real model may safely answer without emitting any
violation. The helper now accepts exactly the two evidence-backed safe states
described above. The dedicated tests cover both safe states and reject a missing
target, unauthorized included context, an answered violation, and a blocked
result without blocking evidence. The separate Canary step remains strictly
blocked.

### Final evidence-boundary corrections

- Health readiness now requires overall `healthy`,
  `evidence_readiness=true`, PostgreSQL storage `up`, and Ollama `up`.
  Degraded, SQLite, or dependency-down states continue polling until the fixed
  health deadline.
- The strict Canary step accepts blocking evidence only when its type is
  `document_canary` or `system_canary`; a protected-fragment detection cannot be
  substituted for the Canary demonstration.
- Reviewer QA now proves that at least one declared target document was included
  in context with authorization and that every included document is authorized,
  in addition to requiring `outcome=answered`.

Pure tests cover the accepted health state and each rejected dependency drift,
both Canary types and an incorrect detection type, and reviewer target-missing
and unauthorized-context failures.

The final focused helper test exited `0` with `32 passed in 0.66s`; the following
`git diff --check` also exited `0`.
