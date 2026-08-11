# DataGuard Phase 6 final architecture acceptance

- Date: 2026-08-11 (Asia/Shanghai)
- Reviewed candidate: `main@bbaadd76d03a701c9f9783b905315f84de16e49c`
- Evidence run: `51790e29-93a5-49f1-81d7-b866bb8cd881`
- Decision: **PASS - authorize the local DataGuard V1 release commit and `v1.0.0` tag**
- Remote publication: deferred by the user

## Final requirement trace

The original seven-stage roadmap is complete. Earlier architecture and
independent-test records establish the project charter, threat model, synthetic
data governance, typed contracts, local Ollama adapter, paired RAG controls,
audit/report pipeline, recovery semantics, and Docker/PostgreSQL delivery. This
review closes Phase 6 against the current repository and the archived evidence,
not against development intent or an unarchived runtime result.

| Final requirement | Authoritative evidence | Result |
| --- | --- | --- |
| Fixed-manifest real evidence on PostgreSQL | archived [experiment manifest](../../reports/v1.0.0/experiment-manifest.v1.json), run above, and [independent test](../testing/TEST_PHASE6_FINAL_EVIDENCE_2026-08-11.md) | Pass |
| Complete paired execution | 62 scenarios, 124 mode results, failed/indeterminate 0 | Pass |
| Baseline attacks remain measurable | 27/32 (84.375%); direct 8/8, indirect 3/8, cross-role 8/8, system inducement 8/8 | Pass |
| Guarded final disclosure | final leaks 0; unauthorized context documents 0 | Pass |
| Legitimate utility | authorized QA 25/30 (83.33%); false rejection 1/30 (3.33%) | Pass |
| Report eligibility | strict manifest, comparability, overall, and `portfolio_eligible` all true | Pass |
| Report integrity | canonical JSON, deterministic HTML and manifest match [SHA256SUMS](../../reports/v1.0.0/SHA256SUMS) | Pass |
| Audit and privacy | 126 events/124 trace bindings; no raw columns; tested fixture/resource values hit zero in PostgreSQL and container logs | Pass |
| Real dependency delivery | Compose contains API and private PostgreSQL only; both healthy; API reaches host Ollama 0.32.8 and fixed model digests | Pass |
| Automated regression | independent full pytest 764 passed; delivery/demo focused suite 38 passed | Pass |
| README and reproducibility | required sections, fixed metrics, archive links, model/license boundary, demo and limitations are present | Pass |
| Evidence-bounded portfolio wording | [portfolio summary](../delivery/PORTFOLIO_SUMMARY.md) limits every claim to the fixed synthetic run | Pass |

The canonical JSON SHA-256 is
`d37a3bc46a9ceb5e156988d185072c194fa8caefc826571067e214017fb7d2c9`;
the deterministic HTML SHA-256 is
`dfea2bc52bee690420dd08edc21045cbad93585e2e6ee01bda85a032aec165f4`;
and the strict manifest SHA-256 is
`704a348960d2abed30bcf9dbf63a61cbf9c567c78a1a3e099d55a7308d0dfeb4`.
Independent validation accepted Draft 2020-12 plus format checking and returned
zero report-semantic issues. Archive re-hashing and fixture validation also
passed at this review point.

## Architecture conformance

The accepted implementation preserves the intended comparison. Baseline
retrieves across the full corpus and observes output violations; guarded
pre-filters by role, marks and isolates untrusted document content, keeps system,
document and query messages separate, applies the same whole-output detector,
discards violating output, and writes only minimized audit evidence. The final
retrieval-topic correction changed synthetic titles and linked questions so the
benchmark actually delivers intended documents; it did not change document
content, authorization, expected assertions, top-k, models, prompts, detector,
report gates, or public contracts.

No real credentials, enterprise data, user data, API keys, or production
documents enter the evidence. Ollama remains a separately managed host service;
Compose contains no Ollama container, hidden simulator, worker, or Docker socket.

## Accepted residual risks

- Results establish only the committed `synthetic-v1` corpus, recorded scenarios,
  fixed manifest, Ollama 0.32.8, and archived model digests. They do not establish
  general prompt-injection safety, production readiness, compliance, or behavior
  on real data.
- Dependency health is cached at application startup. Database-dependent routes
  fail closed during an outage, but `/health` may show its prior startup snapshot
  until restart.
- The QA rate is 83.33%, one passing case above the 80% gate; model/runtime drift
  can change this result and therefore always requires a new manifest and report.
- One authorized QA case was blocked. This is represented in the 3.33% measured
  false-rejection rate and was not reclassified or hidden.
- Third-party model terms are outside the repository MIT license and remain an
  operator responsibility.
- Remote Git publication is intentionally deferred. The accepted local history,
  evidence archive, and tag can be pushed later as one explicit operator action.

## Release decision

All required evidence is present and mutually bound, all fixed gates pass, open
blocking/high/medium/low product defects are zero, and remaining limitations are
explicit. The architecture owner therefore authorizes updating the release
status, committing this acceptance, and creating the local `v1.0.0` tag. No
further data, model, policy, threshold, or report change is authorized for this
release candidate.
