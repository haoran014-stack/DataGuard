# DataGuard Phase 4 architecture acceptance

- Date: 2026-08-11 (Asia/Shanghai)
- Authority: `docs/architecture/SEVEN_STAGE_ROADMAP.md`
- Recovery fix: `bdf30e1` (`fix: recover queued evaluations safely`)
- Real-run evidence: `dc4a61c` (`test: verify roadmap phase 4 real evaluation`)
- Decision: **ACCEPTED - ORIGINAL ROADMAP PHASE 4 COMPLETE**

## Accepted evidence

The production runner completed one real exploratory run using the Phase 2
accepted Ollama/model/index facts and SQLite. No fixture, prompt, policy,
detector, model, parameter, or threshold was changed after observing results.

| Gate | Result |
| --- | --- |
| Run | `94e82e98-88ff-43ca-a98f-768d6bb347ba`, completed 62/62 |
| Mode results | 124, failed 0, indeterminate 0 |
| Pairing | Baseline then Guarded with one comparability key; comparability passed |
| Scenario distribution | 30 QA; four attack families x 8; each attack family 4 English/4 Chinese |
| Canonical report | 236,846 bytes; SHA-256 `116845902541087bb422073dbaa4159072f6217cf2140cf2faaaed6778f2c67e` |
| Report validation | Draft 2020-12 and semantic validation: 0 issues |
| HTML | Deterministic rendering of the same report; SHA-256 `7296907825582ea92d1cbbd7af25ac0bca0143b9dba2f92c4891b18b5489b124` |
| Audit | 126 events: 124 mode output events, one created, one terminal; trace/evidence binding complete |
| Privacy | No question, document body, Canary, protected fragment, or system content bytes persisted |
| Recovery | Persisted queued runs resume FIFO; running becomes interrupted; publication faults roll back safely |
| Independent defects | One Medium recovery-cleanup defect found and closed before the real run; open defects 0 |

## Exploratory result boundary

- Baseline ASR: 25/32 (78.125%): direct 8/8, indirect 1/8,
  cross-role 8/8, system-inducement 8/8.
- Guarded attack success/final leak: 0/32.
- Guarded unauthorized context documents: 0.
- Guarded authorized-QA pass: 13/30 (43.33%).
- Guarded false rejection: 0/30.
- `overall_passed=false`, `strict_manifest_passed=false`, and
  `portfolio_eligible=false` are correct for this exploratory SQLite run.

Phase 4 requires a complete honest exploratory comparison, not the Phase 6
portfolio threshold. The 43.33% QA result is therefore accepted as a Phase 4
finding but is an explicit blocker for Phase 6 evidence, whose minimum is 80%.
It must be improved through a reviewed Phase 5/6 change and a new comparable
run, never by rewriting this report.

Full evidence is in
[`TEST_PHASE4_REAL_RUN_2026-08-11.md`](../testing/TEST_PHASE4_REAL_RUN_2026-08-11.md).

## Next gate

Phase 5 is authorized: PostgreSQL parity, Docker/Compose runtime, evidence
profile and strict manifest preflight. Phase 5 must preserve this exploratory
report and must not claim V1 evidence. Before Phase 6, the legitimate-QA failure
causes must be classified and corrected without weakening authorization,
Canary detection, attack scenarios, or report gates.
