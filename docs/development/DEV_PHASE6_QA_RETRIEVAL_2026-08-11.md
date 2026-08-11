# Phase 6 development record - authorized-QA retrieval anchors

## Scope and evidence basis

- Baseline: `main@021068a99d506326edaf5a84397f6d3ed7988a0b`, initially clean.
- The prior minimized report diagnosis attributed 16 of 17 guarded authorized-QA
  failures to the target document being absent from top-4 context.
- This batch changes only those 16 authorized-QA `question` values. Each keeps
  its original language and request meaning while replacing the document-ID
  reference with the target document's complete, non-sensitive title.
- No real model call or evaluation run was performed. This is a data-quality
  correction and unit-validation record, not evidence that QA performance
  improved.

## Digest change

| Artifact | Before | After |
|---|---|---|
| Scenario set exact UTF-8/LF SHA-256 | `174866e7c079665894c761b5a6219777227d3e07eaa5d7d04d97300e571fbdcd` | `85f9e4f4e01100bd3cc65c3b6f5d617dcabbc7ef28e4f9725fd49f73560f5c35` |
| Corpus SHA-256 | `77a3615a2bac7f3c9962e39b6c157c21c7703ce6416852af5acc2beadca01571` | unchanged |
| Identity SHA-256 | `594203461e9c5a569d1f805ded0eb58c9f1b5fa509b2c6df1d9811135e204c27` | unchanged |

Any later experiment manifest and comparability key must bind the new scenario
SHA. The corpus and vector index do not require rebuilding because neither the
corpus nor its embedding inputs changed.

## Files and boundaries

| File | Change |
|---|---|
| `data/synthetic-v1/scenarios.yaml` | Updated only the diagnosed 16 authorized-QA questions with their target titles. |
| `tests/unit/test_fixture_loading.py` | Added a deterministic title-anchor and prohibited-content regression for the fixed 16-ID set. |

The regression normalizes title and question with Unicode NFKC plus casefold,
then requires the complete target title in the question. It dynamically reads
fixture values and proves the corrected questions contain none of their
expected assertions and none of any corpus Canary or protected-fragment value.
It also retains the existing schema, typed loading, semantic validation, 62-case
distribution, 30 authorized-QA, and four attack-family 8-case checks.

Explicitly unchanged: scenario IDs, language, subject, target and forbidden
evidence IDs, expected assertions, all attack scenarios, corpus documents,
roles, top-k, prompts, detector/policy, product logic, public contracts, models,
and generation/retrieval settings.

## Development-side checks

| Command | Exit | Result |
|---|---:|---|
| `.\.venv\Scripts\python -m pytest tests\unit\test_fixture_loading.py tests\unit\test_fixture_semantics.py -q` | `0` | `37 passed in 6.34s`. |
| `.\.venv\Scripts\python -m dataguard.validation` | `0` | 6 identities, 30 documents, 62 scenarios, zero issues; new scenario SHA reported above. |

No commit or push was performed. A later controlled real-model run is required
to measure retrieval and QA effects and must recheck every locked security gate;
this development record makes no projected result a measured claim.
