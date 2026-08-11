# DataGuard portfolio summary

Built and evaluated a local synthetic RAG security experiment that compared a
deliberately vulnerable cross-role retrieval baseline with role-prefiltering,
untrusted-document and message isolation, whole-output Canary/protected-fragment
blocking, and minimized audit/report evidence; in one fixed-manifest Ollama
`0.32.8` run, baseline attacks succeeded in 27/32 cases while the guarded path
had zero final leaks and zero unauthorized-context documents with authorized QA
passing 25/30 cases. These measurements are limited to the committed synthetic
fixtures, recorded model digests, and this archived run; they are not a claim of
production or general prompt-injection safety. Evidence:
[independent report](../testing/TEST_PHASE6_FINAL_EVIDENCE_2026-08-11.md) and
[archived artifacts](../../reports/v1.0.0/SHA256SUMS).
