# DataGuard Development Work Record — `<work_id>`

## Record metadata

- Date/time and timezone:
- Development owner:
- Requirement/work item IDs:
- Repository root:
- Baseline branch and commit SHA:
- Working-tree status before work:
- Scope:
- Explicit non-goals:

## Inputs and applicable instructions

- Applicable `AGENTS.md` files:
- Architecture/security documents reviewed:
- Contract versions reviewed:
- Existing user/Agent changes preserved:

## Impact analysis

| Area | Impact | Compatibility decision |
| --- | --- | --- |
| HTTP API | | none / additive / breaking |
| Error codes | | none / additive / breaking |
| Metrics | | none / additive / breaking |
| Report/manifest/data schemas | | none / additive / breaking |
| RAG flow/trust boundaries | | none / accepted deviation / rejected deviation |
| Database/storage | | none / migration required |

## Implementation summary

| File | Change | Reason |
| --- | --- | --- |
| | | |

## Fixed architecture conformance

- [ ] Caller supplies `subject_id` only; role resolves from `synthetic-v1`.
- [ ] Baseline searches all 30 documents and permits unauthorized context.
- [ ] Baseline uses weak isolation and the shared detector observe-only.
- [ ] Guarded filters `allowed_roles` before top-4 vector retrieval.
- [ ] Guarded uses JSON untrusted-document boundary and separate
      system/document/query messages.
- [ ] Detector scans untruncated full output after versioned NFKC/casefold/
      zero-width/whitespace normalization.
- [ ] Guarded violation discards whole raw output, persists none, and returns the
      exact fixed blocked reply; no partial output is returned.
- [ ] Local Ollama tags/digests, embedding dimensions, and locked settings match.
- [ ] Raw question/document/context/prompt/reply/marker literals are not persisted.
- [ ] Exploratory SQLite and evidence PostgreSQL boundaries are preserved.

## Development-side checks

This section records implementation checks, not independent test or architecture
acceptance.

| Command | Exit code | Result/evidence |
| --- | ---: | --- |
| | | |

## Data and security review

- Synthetic fixture/schema impact:
- Evidence minimization impact:
- Secret/raw-content scan:
- Dependency/supply-chain impact:
- Known limitations or residual risks:

## Handoff

- Files requiring independent test:
- Contract/gate cases affected:
- Migrations/configuration required:
- Unresolved questions:
- Next development context:

No development record constitutes test acceptance, architecture acceptance,
release approval, commit, or push evidence.
