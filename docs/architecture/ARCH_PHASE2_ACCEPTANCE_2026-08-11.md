# DataGuard Phase 2 architecture acceptance

- Date: 2026-08-11 (Asia/Shanghai)
- Authority: `docs/architecture/SEVEN_STAGE_ROADMAP.md`
- Product commit: `d81851b` (`fix: support current Ollama phase 2 protocol`)
- Decision: **ACCEPTED - ORIGINAL ROADMAP PHASE 2 COMPLETE**

## Scope decision

The original roadmap Phase 2 gate is closed. The accepted implementation uses
the fixed local generation and embedding models, a canonical 30-document index,
deterministic top-4 retrieval, deliberately unguarded Baseline RAG, minimized
observe-only detection, and explicit dependency failure. This decision does not
accept Guarded controls, paired evaluation, PostgreSQL, Docker, or V1 evidence.

## Direct evidence

| Gate | Accepted evidence |
| --- | --- |
| Local runtime | Ollama `0.32.8` on loopback |
| Generation model | `qwen2.5:3b-instruct`, digest `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b` |
| Embedding model | `qwen3-embedding:0.6b`, digest `ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d` |
| Embedding/index | 1024 dimensions, 30 documents, artifact SHA-256 `b5add8cd106e5f2124ab81db73fb0b8867114f620ed379ef8310deadf8645dfa` |
| Protocol compatibility | Current additive `capabilities` and `tensors` fields are bounded, validated, discarded, and covered by 109 adapter tests |
| Repeatability | Two identical real Baseline requests returned the same ordered top-4 document IDs |
| Deliberately weak Baseline | Both requests included four unauthorized documents, with zero authorization denials |
| Controlled leak | Both real replies produced `unauthorized_protected_fragment`, `violation=true`, `action=observed`, while remaining `answered`; no literal was retained |
| Dependency failure | Unreachable Ollama produced health 503 and chat 503 `ollama_unavailable`, with no reply, reflection, simulator, or fallback |
| Independent defects | Blocking 0, High 0, Medium 0, Low 0 |

The full minimized independent record is
[`TEST_PHASE2_REAL_OLLAMA_2026-08-11.md`](../testing/TEST_PHASE2_REAL_OLLAMA_2026-08-11.md).

## Architecture review

- The compatibility repair does not open the entire Ollama response shape. It
  recognizes only two current additive fields, applies record/string/rank and
  global response-byte bounds, and discards their contents after validation.
- Exact model names, digests, required model set, embedding dimension, local URL,
  content type, JSON shape, status, timeout, and response limits remain closed.
- Baseline's authorization weakness remains restricted to the committed
  synthetic local experiment. It is observable in minimized audit evidence and
  is not reused as the Guarded policy.
- No raw model reply, document body, Canary, or protected-fragment literal was
  copied into Git evidence.

## Environment deviation

Port 8000 was occupied by Microsoft IIS. The independent test did not stop or
modify IIS; it ran the identical production application factory and lifespan on
loopback port 18000. This listener-only difference does not alter the accepted
six-route protocol or Phase 2 behavior and is recorded as a non-product
environment limitation.

## Next gate

Phase 3 is now authorized: real Guarded role filtering, message isolation,
whole-output blocking, minimized chat audit, and representative legal/attack
acceptance. Phase 2 artifacts and model facts must remain fixed while Phase 3 is
tested; they may not be retuned to make Guarded results pass.
