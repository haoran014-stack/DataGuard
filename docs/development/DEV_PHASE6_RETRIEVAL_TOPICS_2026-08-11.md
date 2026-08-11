# Phase 6 development record - unique retrieval topics

## Scope and rationale

- Baseline: the accepted pre-change fixture had corpus SHA
  `77a3615a2bac7f3c9962e39b6c157c21c7703ce6416852af5acc2beadca01571`
  and scenario SHA
  `85f9e4f4e01100bd3cc65c3b6f5d617dcabbc7ef28e4f9725fd49f73560f5c35`.
- Sanitized evidence showed 12 authorized-QA targets still missed top-4 after
  generic title anchoring, and all eight indirect targets missed Baseline top-4.
- The union contains 15 documents. Only their titles were changed, using unique,
  language-matched, non-sensitive topic names. Their content, authorization,
  classification, Canary/protected-fragment metadata, and adversarial flags are
  byte/field-equivalent to the HEAD baseline.
- Updated 15 one-per-document authorized-QA questions and all eight indirect
  questions to reference the complete new target title while preserving language
  and intent.

## Explicit boundaries

- No expected assertion, Canary, protected fragment, or adversarial instruction
  target value was copied into a question or title.
- No document content, role, classification, adversarial flag, scenario ID,
  subject, target/evidence ID, expected assertion, other attack family, top-k,
  product code, or public contract changed.
- No model, API, Docker, database, or evaluation was run. No commit or push was
  performed.

## Files and counts

| File | Change |
|---|---|
| `data/synthetic-v1/corpus.yaml` | 15 document titles changed. |
| `data/synthetic-v1/scenarios.yaml` | 15 authorized-QA and 8 indirect questions changed. |
| `tests/unit/test_fixture_loading.py` | Added exact-set, title uniqueness/linkage, prohibited-value, and non-title document integrity checks. |

The test stores SHA-256 values for each affected document's complete validated
mapping with only `title` removed. This locks every other document field to the
HEAD baseline without reproducing raw fixture values in test output.

## Resulting digests

| Artifact | Before | After |
|---|---|---|
| Corpus exact UTF-8/LF SHA-256 | `77a3615a2bac7f3c9962e39b6c157c21c7703ce6416852af5acc2beadca01571` | `a61bdadc5227796987f65fe82e4fe0327eb3b1a1df0b3f1125e05f2d2652def9` |
| Scenario exact UTF-8/LF SHA-256 | `85f9e4f4e01100bd3cc65c3b6f5d617dcabbc7ef28e4f9725fd49f73560f5c35` | `2376cc4ab2a83949b229a2fe7b33d6946466ecca65cf760c129d8230edc3ba87` |
| Identity SHA-256 | `594203461e9c5a569d1f805ded0eb58c9f1b5fa509b2c6df1d9811135e204c27` | unchanged |

Because title is part of the exact document embedding input, the old vector
index is stale by construction. Any later run must explicitly rebuild the index,
generate a new strict manifest binding both new fixture digests and the new
index digest, and pass `verify-artifacts` before startup. No existing manifest or
report can be reused as evidence for this fixture revision.

## Development-side checks

| Command | Exit | Evidence |
|---|---:|---|
| Initial fixture tests | nonzero | 37 passed, 1 integrity-hash failure caused by PowerShell transcoding of HEAD Chinese YAML during test-constant preparation. |
| Python raw-byte HEAD digest recalculation | `0` | Corrected only the affected Chinese integrity constants; data files were unchanged. |
| `.\.venv\Scripts\python -m pytest tests\unit\test_fixture_loading.py tests\unit\test_fixture_semantics.py -q --basetemp .pytest_cache\retrieval-topics` | `0` | `38 passed in 6.62s`. |
| `.\.venv\Scripts\python -m dataguard.validation` | `0` | 6 identities, 30 documents, 62 scenarios, zero issues; new digests reported above. |

These are development-side fixture checks, not a retrieval-performance claim or
independent acceptance. Only a new complete real-model run can measure impact.
