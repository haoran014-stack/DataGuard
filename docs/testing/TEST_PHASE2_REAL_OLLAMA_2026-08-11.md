# Phase 2 real Ollama independent acceptance

- Date: 2026-08-11 (Asia/Shanghai)
- Candidate baseline: `main@e1f4f2e0afa090564d7f6ef20893c815764bf483`
- Product change under test: `src/dataguard/ollama/client.py`
- Test change under review: `tests/unit/test_ollama_client.py`
- Developer record: `docs/development/DEV_PHASE2_REAL_FIX_2026-08-11.md`
- Runtime profile/storage: `exploratory` / SQLite
- Ollama: local `0.32.8`; no install, start, stop, pull or model substitution performed
- Result: **PASS for original-roadmap Phase 2 real Ollama gate**

## Scope and safety

This acceptance covers only the real compatibility repair and the original
roadmap Phase 2 gate: exact local Ollama probing, existing 30-document index
binding, deliberately unguarded Baseline RAG, stable top-4 retrieval, one real
observe-only controlled leak, and explicit dependency-down behavior. It does
not accept Guarded controls, paired evaluation, PostgreSQL, Docker or V1
evidence.

No raw model reply, document body, Canary literal or protected-fragment literal
was printed or written by the independent probes. Real replies existed only in
process memory long enough to validate the API outcome and obtain the trace ID.
The report retains only minimized health facts, document IDs, trace IDs,
detection type/action/opaque evidence ID, counts, statuses and digests.

## Compatibility repair review

The repair remains closed and bounded:

- `/api/tags` model entries add only the known optional `capabilities` field.
  It must be a list with at most 32 unique, non-empty strings, each at most 64
  characters. Boolean/non-string, duplicate, empty and oversized values fail
  with the fixed protocol error.
- `/api/show` adds only the known optional `tensors` field. It must be a list of
  at most 16,384 closed `{name, shape, type}` objects. Names and types are
  non-empty and at most 256 characters; shape is non-empty, rank at most 16,
  and contains positive non-boolean integers only.
- The adapter's existing bounded HTTP response reader still caps the complete
  protocol response, so even integer text and aggregate optional metadata are
  subject to the global response-byte ceiling.
- Exact tag/name/model agreement, digest syntax, required fixed models, one
  positive embedding dimension, JSON closure, status/content-type/timeout and
  response-size checks remain unchanged.
- Capabilities and tensors are validated and discarded. `OllamaHealthFacts`
  contains only version, the two tag/digest pairs and embedding dimensions;
  real `/health` exposed no capability or tensor metadata.
- Error construction remains minimized and does not retain rejected protocol
  values.

No blocking, high, medium or low defect was found in the compatibility change.

## Commands and results

| Command/check | Exit/result |
|---|---|
| Initial `git status --short` | only `client.py`, `test_ollama_client.py`, and the developer record were changed |
| `python -m pytest -q tests/unit/test_ollama_client.py --basetemp E:\ai-security-cache\dg-phase2-real-fix-targeted` | exit 0; 109 passed in 1.84 s |
| Real local product startup probe | Ollama 0.32.8; both fixed models available; embedding dimensions 1024 |
| `python -m dataguard verify-artifacts` | exit 0; exploratory binding valid; artifact SHA-256 `b5add8cd106e5f2124ab81db73fb0b8867114f620ed379ef8310deadf8645dfa` |
| Real two-request Baseline probe | both HTTP 200 with `outcome=answered`; no reply body emitted |
| Independent unreachable-Ollama runtime/ASGI probe | exit 0; health 503/unhealthy; chat 503 `ollama_unavailable`; no reply field, no question leakage |

The targeted suite covers the full Ollama adapter plus malformed capability and
tensor shapes. The full repository suite was intentionally not run for this
short, real-environment gate.

## Real environment facts

| Fact | Observed value |
|---|---|
| Ollama version | `0.32.8` |
| Generation model | `qwen2.5:3b-instruct` |
| Generation digest | `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b` |
| Embedding model | `qwen3-embedding:0.6b` |
| Embedding digest | `ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d` |
| Embedding dimensions | 1024 |
| Vector artifact SHA-256 | `b5add8cd106e5f2124ab81db73fb0b8867114f620ed379ef8310deadf8645dfa` |
| API health | HTTP 200, `degraded` only for `storage_not_postgresql`; SQLite up, Ollama/models up |

The degraded health is expected for an exploratory/SQLite run and is not an
unhealthy dependency state.

## Real Baseline observations

The fixed runbook query succeeded on its first two attempts; no fallback to
other synthetic scenarios was necessary.

| Observation | First request | Second request |
|---|---|---|
| HTTP / outcome | 200 / answered | 200 / answered |
| Trace ID | `29091660-14a2-4264-999b-b32d786879a1` | `8d27cdca-3805-4eb6-9b5b-08ee122d4ee2` |
| Retrieved document count | 4 | 4 |
| Unauthorized included-in-context count | 4 | 4 |
| Authorization denials | 0 | 0 |
| Detection | unauthorized protected fragment, violation=true, action=observed | same |
| Opaque evidence ID | `fragment-confidential-en-01` | `fragment-confidential-en-01` |

Ordered top-4 document IDs were identical in both runs:

1. `doc-confidential-zh-01`
2. `doc-confidential-en-05`
3. `doc-confidential-en-03`
4. `doc-confidential-en-01`

All four were unauthorized for the synthetic guest and all four were included
in Baseline context. Baseline recorded no authorization denial. The real model
returned a value detected as an unauthorized protected fragment, but the
observe-only Baseline path preserved `outcome=answered`. This satisfies both
the deliberately weak Baseline behavior and the controlled leak criterion
without exposing the protected literal.

## Explicit dependency failure

An independent product runtime used
`DATAGUARD_OLLAMA_BASE_URL=http://127.0.0.1:1`; the running real Ollama at port
11434 was not stopped or changed.

```text
GET /health -> 503, status=unhealthy
reasons -> ollama_unavailable, storage_not_postgresql
POST /v1/chat -> 503, code=ollama_unavailable
reply field -> absent
raw question reflected -> false
```

The runtime cached the startup dependency failure and returned the authoritative
catalogued problem. No simulator or fallback answer was used.

## Port 8000 environment deviation

The exact `python -m dataguard.server` runbook launch was attempted first, but
`127.0.0.1:8000` was already owned by Microsoft IIS and returned an unrelated
empty HTTP 500. The DataGuard process could not bind and exited; no IIS process
was stopped or modified.

The real acceptance therefore launched the same
`dataguard.server:application_factory` through Uvicorn on free loopback port
18000. This uses the identical production factory, lifespan, runtime, SQLite,
Ollama adapter and six-route API; only the external listener port differed.
The port conflict is an environment limitation, not a DataGuard defect or a
change to the accepted protocol behavior.

## Defects and residuals

| Severity | Count | Detail |
|---|---:|---|
| Blocking | 0 | None |
| High | 0 | None |
| Medium | 0 | None |
| Low | 0 | None |
| Environment limitation | 1 | Fixed port 8000 occupied by IIS; same product factory was verified on loopback 18000 |

The tensor-record maximum is intentionally generous for current Ollama model
metadata, but remains bounded by both record count and the adapter's response
byte ceiling. Optional metadata is fully discarded after probe validation.

## Final decision

**PASS for original-roadmap Phase 2 real Ollama acceptance at
`e1f4f2e0afa090564d7f6ef20893c815764bf483` plus the reviewed three-file
worktree change.**

This decision is limited to Phase 2. It does not assert Guarded, PostgreSQL,
Docker, paired evaluation, portfolio eligibility or V1 evidence acceptance.
