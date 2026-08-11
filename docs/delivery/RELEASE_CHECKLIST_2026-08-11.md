# DataGuard V1 release checklist - 2026-08-11

This checklist maps the seven-stage roadmap's Phase 6 deliverables and gates to
the accepted evidence for run `51790e29-93a5-49f1-81d7-b866bb8cd881`. The
[final architecture decision](../architecture/ARCH_PHASE6_FINAL_ACCEPTANCE_2026-08-11.md)
authorizes the local V1 release; remote publication remains user-controlled.

## Delivery mapping

| Roadmap item | Evidence | Status |
| --- | --- | --- |
| Real evidence run under a fixed manifest and PostgreSQL | Archived [canonical JSON](../../reports/v1.0.0/dataguard-evidence.json) and [strict manifest](../../reports/v1.0.0/experiment-manifest.v1.json) | Complete |
| Sanitized JSON, static HTML, and SHA-256 manifest | [JSON](../../reports/v1.0.0/dataguard-evidence.json), [HTML](../../reports/v1.0.0/dataguard-evidence.html), [SHA256SUMS](../../reports/v1.0.0/SHA256SUMS) | Complete |
| README problem/non-goals, threat model, architecture, provenance/licensing, install/run, reproduction, metrics, limitations, and security boundary | [README](../../README.md) and its linked normative documents | Complete |
| Demonstration covers baseline cross-role risk, guarded filtering, indirect injection, Canary blocking, authorized reviewer QA, audit, and reports | [`scripts/demo.ps1`](../../scripts/demo.ps1), [`scripts/demo_client.py`](../../scripts/demo_client.py), and [demo development record](../development/DEV_PHASE6_DEMO_COVERAGE_2026-08-11.md) | Complete |
| Release checklist and final independent evidence | This checklist and [TEST_PHASE6_FINAL_EVIDENCE](../testing/TEST_PHASE6_FINAL_EVIDENCE_2026-08-11.md) | Complete |
| Evidence-backed portfolio wording | [Portfolio summary](PORTFOLIO_SUMMARY.md) | Complete |

## Fixed evidence gates

All numerical results below are bounded to the archived `synthetic-v1` run,
strict manifest, Ollama `0.32.8`, and the model digests recorded in that
manifest. Independent recomputation and privacy checks are documented in
[TEST_PHASE6_FINAL_EVIDENCE](../testing/TEST_PHASE6_FINAL_EVIDENCE_2026-08-11.md).

| Gate | Required | Result | Status |
| --- | ---: | ---: | --- |
| Baseline direct prompt injection successes | at least 1/8 | 8/8 | Pass |
| Baseline indirect document injection successes | at least 1/8 | 3/8 | Pass |
| Baseline cross-role retrieval successes | at least 1/8 | 8/8 | Pass |
| Baseline system-prompt inducement successes | at least 1/8 | 8/8 | Pass |
| Baseline total ASR | at least 20% | 27/32 (84.375%) | Pass |
| Guarded final leaks | 0 | 0 | Pass |
| Guarded unauthorized context documents | 0 | 0 | Pass |
| Guarded authorized-QA pass rate | at least 80% | 25/30 (83.33%) | Pass |
| Guarded false-rejection rate | at most 10% | 1/30 (3.33%) | Pass |
| Indeterminate mode results | 0 | 0 | Pass |
| Report portfolio eligibility | `true` | `true` | Pass |
| JSON/HTML/manifest archive hashes | match `SHA256SUMS` and independent evidence | all matched | Pass |
| README measurements trace to archived evidence | every reported number links to the archive and independent report | mapped in README | Complete |
| Unit, real-model, PostgreSQL, and manifest evidence | 764 deterministic tests; independent real dependency/artifact checks passed | recorded in independent report | Pass |
| Final architecture requirements and residual-risk acceptance | [final architecture decision](../architecture/ARCH_PHASE6_FINAL_ACCEPTANCE_2026-08-11.md) | accepted | **Complete** |
| Create annotated `v1.0.0` tag | authorized for the final release commit; verify with `git tag --points-at HEAD` | release procedure | **Authorized** |
| Remote push of release commit/tag | user-controlled publication step | deferred by user | **Deferred** |

## Reverification commands

Run from the repository root in the recorded Python 3.12 environment. These
commands do not invoke the model or submit another evaluation.

```powershell
Get-FileHash -Algorithm SHA256 reports/v1.0.0/dataguard-evidence.json
Get-FileHash -Algorithm SHA256 reports/v1.0.0/dataguard-evidence.html
Get-FileHash -Algorithm SHA256 reports/v1.0.0/experiment-manifest.v1.json
Get-Content reports/v1.0.0/SHA256SUMS
.\.venv\Scripts\python -m pytest tests/unit/test_delivery_files.py tests/unit/test_demo_client.py
git diff --check
```

Expected archive hashes are recorded only in
[`reports/v1.0.0/SHA256SUMS`](../../reports/v1.0.0/SHA256SUMS). The final
architecture decision authorizes the local release commit and annotated tag;
it does not authorize a remote push.
