# Development work record: Phase 2 real Ollama compatibility fix

## Scope

- Date: 2026-08-11
- Baseline: clean `main@e1f4f2e0afa090564d7f6ef20893c815764bf483`
- Runtime: local Ollama 0.32.8, no model pull or substitution
- Profile/storage: `exploratory` / SQLite
- Boundary: original roadmap Phase 2 probe and index-build blocker only; no
  Guarded, audit, evaluation, report, PostgreSQL, Docker, or other later-phase
  behavior was added.

## Failure and diagnosis

The operator-visible command `python -m dataguard build-index` returned exit 1
with only the intended minimized `artifact_preparation_failed` JSON. No partial
index existed. A content-safe internal diagnostic identified
`model_protocol_error`. The request sequence stopped after `/api/tags`, before
`/api/show` or `/api/embed`.

Ollama 0.32.8 adds a `capabilities` list to each `/api/tags` model object. The
adapter's closed tag shape did not yet recognize that field. After closing that
compatibility point, the real probe reached `/api/show`, which exposed a second
0.32.8 addition: a `tensors` list is returned even when the request explicitly
uses `verbose=false`.

## Minimal fix

`src/dataguard/ollama/client.py` now accepts only these two known additions:

- tag `capabilities`: a bounded list of unique, non-empty bounded strings;
- show `tensors`: a bounded list of closed `{name, shape, type}` objects, with
  bounded strings and a non-empty bounded rank of positive non-boolean integer
  dimensions.

Critical protocol fields remain strict: exact tag/name/model agreement, digest
shape, required models, unique positive embedding dimension, response bytes,
JSON closure, and all existing timeout/status rules. Capabilities and tensor
metadata are validated and discarded. They do not enter `OllamaHealthFacts`,
the vector artifact, audit, errors, reports, logs, or this record.

`tests/unit/test_ollama_client.py` now uses the real 0.32.8 content type and
representative tag/show shapes. Negative cases cover malformed, duplicated,
oversized, unknown, boolean, zero, and empty values without echoing the raw test
sentinel.

## Developer verification

| Command/check | Exit code | Result |
| --- | ---: | --- |
| Ollama adapter targeted test file | 0 | 109 passed in 1.94s |
| Real local `OllamaClient.probe()` | 0 | Ollama 0.32.8; exact two model tags/digests; embedding dimension 1024 |
| Real `python -m dataguard build-index` | 0 | 30 documents, dimension 1024, artifact SHA-256 `b5add8cd106e5f2124ab81db73fb0b8867114f620ed379ef8310deadf8645dfa` |
| Real `python -m dataguard verify-artifacts` | 0 | Exploratory artifact binding valid; same artifact SHA-256 |

Observed local model facts:

- generation tag `qwen2.5:3b-instruct`, digest
  `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b`;
- embedding tag `qwen3-embedding:0.6b`, digest
  `ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d`;
- embedding dimension 1024.

The real build sent the accepted synthetic corpus only to the separately
managed loopback Ollama and created the ignored canonical local artifact. No
question, document body, Canary, protected fragment, tensor name, or model
response was printed or copied into this record. Per the requested short-batch
boundary, the full suite and real HTTP chat acceptance were not run; the
independent tester will perform broader verification. No commit or push was
performed.
