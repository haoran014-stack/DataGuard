# DataGuard Phase 3 architecture acceptance

- Date: 2026-08-11 (Asia/Shanghai)
- Authority: `docs/architecture/SEVEN_STAGE_ROADMAP.md`
- Evidence commit: `96a6bfb` (`test: verify roadmap phase 3 guarded controls`)
- Decision: **ACCEPTED - ORIGINAL ROADMAP PHASE 3 COMPLETE**

## Accepted behavior

- Server-side synthetic subject resolution and cumulative role authorization.
- Guarded pre-retrieval role filtering; unauthorized documents never enter
  vector ranking or context.
- Closed JSON document boundaries and separate system/document/query messages.
- Document/System Canary and role-aware protected-fragment whole-output checks.
- Baseline observe-only behavior and Guarded full-reply discard with the exact
  fixed safe reply on a violation.
- Minimized SQLite chat/retrieval/denial/detection audit with bounded filtering
  and cursor pagination.
- Required audit failure remains an explicit dependency failure and never
  returns an otherwise generated reply.

## Real acceptance evidence

An independent fresh-SQLite run used the Phase 2 accepted Ollama/model/index
facts and completed nine real chats: one Baseline/Guarded pair for each fixed
attack family plus one authorized confidential reviewer question.

| Gate | Result |
| --- | --- |
| Four attack families | All represented in real Baseline/Guarded pairs |
| Baseline | All four answered; every detected violation was observe-only |
| Guarded role filter | Each guest request produced 20 pre-retrieval denials |
| Guarded unauthorized context | 0 for every representative request |
| Guarded final leak | 0 for every representative request |
| Fixed blocking | Direct and system-inducement were blocked with the exact fixed safe reply |
| Safe non-blocking | Indirect and cross-role safely answered without final violation |
| Authorized reviewer | Confidential QA answered, four authorized confidential document IDs, no final violation |
| Audit minimization | Fresh database scan over 109 dynamic probes found no question, reply, marker, fragment, or document body |
| Regression | 59/59 targeted tests passed |
| Independent defects | Blocking 0, High 0, Medium 0, Low 0 |

The independent run observed no marker detection for its Baseline indirect case,
while the developer run did. This is recorded model nondeterminism, not a failed
Phase 3 gate: the representative family executed, Baseline remained deliberately
unguarded, and Guarded had zero unauthorized context and zero final violation.
No fixture, model, prompt, policy, detector, or threshold was changed to shape
the result.

Full minimized evidence is in
[`TEST_PHASE3_REAL_GUARDED_2026-08-11.md`](../testing/TEST_PHASE3_REAL_GUARDED_2026-08-11.md).

## Next gate

Phase 4 is authorized: execute all 62 real scenarios as paired Baseline/Guarded
results through the FIFO runner, verify state transitions, sanitized JSON/HTML,
comparability, failure accounting, metrics, and restart behavior. Phase 4 is an
exploratory report gate; it does not yet accept PostgreSQL/Docker evidence or a
V1 portfolio result.
