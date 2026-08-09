# DataGuard Stage 1 Scope and Acceptance Baseline

## 1. Purpose and authority

This document defines the implementation and acceptance boundary for Stage 1:
synthetic fixtures and domain models. It is derived from the Stage 0 contracts,
the `ST0-R02` architecture condition, and the Stage 0 independent-test residual
constraints. It does not revise the public v1 API or experiment gates.

Baseline repository state:

- Branch: `main`
- Starting commit: `a373d50a5dfc0cef8be0efb308f955fe881443c0`
- Corpus/policy version: `synthetic-v1`

If this document conflicts with a machine-readable contract under
`docs/contracts/`, the machine-readable contract remains authoritative and the
conflict must be escalated to architecture review rather than implemented.

## 2. In scope

### S1-ENV — locked local environment contract

- Declare Python 3.12 and exact dependency versions for the Stage 1 stack.
- Provide one documented, repeatable local installation command and one official
  validation command.
- Keep FastAPI and SQLAlchemy in the locked project policy even though Stage 1
  does not expose HTTP or database behavior.
- Do not download or distribute Ollama models in Stage 1.

### S1-DOM — closed domain models

- Implement closed, typed models for roles, classifications, languages, attack
  families, identities, documents, document Canaries, protected fragments,
  expected assertions, scenarios, and their versioned aggregate sets.
- Reject unknown fields, invalid enum values, empty required values, incorrect
  versions, and incorrect fixed distributions.
- Resolve caller role only from the versioned identity table; fixture input never
  supplies an authoritative role alongside `subject_id`.
- Domain code remains independent of FastAPI, SQLAlchemy, Ollama, vector stores,
  and transport/storage adapters.

### S1-DATA — reviewed `synthetic-v1` fixtures

Repository fixtures must contain exactly:

- 6 identities: 2 each for `guest`, `employee`, and `security_reviewer`;
- 30 documents: 10 each for `public`, `internal`, and `confidential`, with 5
  English and 5 Chinese documents inside every classification;
- 62 scenarios: 30 `authorized_qa` and 8 bilingual cases for each of the four
  fixed attack families, with 4 English and 4 Chinese cases per attack family.

Every document must visibly declare its classification, cumulative
`allowed_roles`, language, synthetic source, MIT fixture license, content
warning, one document Canary, and any protected fragments. Every fixture value
must be invented for this repository. No real person, organization, credential,
API key, production identifier, customer/user record, or copied internal text is
permitted.

The fixtures intentionally include fake sensitive-looking markers and prompt
injection text. Adversarial documents must set `adversarial_fixture=true`.

### S1-LOAD — deterministic and safe loading

- Load YAML with duplicate-key rejection; YAML aliases or alternate scalar forms
  must not bypass the closed models.
- Validate each loaded instance against the corresponding Draft 2020-12 JSON
  Schema and the typed domain model before semantic validation.
- Fixture digests are lowercase SHA-256 over the exact committed UTF-8, no-BOM,
  LF file bytes. The literal version remains `synthetic-v1`; changing fixture
  bytes requires an explicit compatibility/version decision before evidence use.
- Validation failures expose stable machine-readable issue codes and structured
  paths, without echoing raw document, question, Canary, protected-fragment, or
  model-output values.

### S1-SEM-DATA — cross-record semantic validation

The validator must reject at least these conditions:

1. duplicate `subject_id`, `doc_id`, `scenario_id`, `canary_id`, or
   `fragment_id` values;
2. a Canary/fragment evidence ID reused anywhere else in the corpus;
3. a protected fragment whose `allowed_roles` differs from its source document;
4. a scenario whose `subject_id` or `attack_target_ids` reference does not exist;
5. a `forbidden_evidence_ids` reference that does not exist in the declared
   corpus evidence set;
6. anything other than exactly one `authorized_qa` scenario per document;
7. an authorized-QA subject that is not allowed to access its target document;
8. an authorized-QA expected assertion that is empty or cannot be anchored to
   its target document content;
9. a cross-role attack whose subject is authorized for every target document;
10. a referenced evidence ID that is unrelated to all declared attack targets.

The validator must return all deterministic issues in a stable order so the same
input yields comparable evidence across runs.

### S1-SEM-REPORT — Stage 0 semantic-validator closure

Stage 1 must provide independently testable semantic validation for report and
error objects even though no runtime report is generated yet. It must enforce:

- rate `value = numerator / denominator`; the report contract requires every
  denominator to be at least one, so a zero denominator is structurally invalid;
- family, summary, prevention-stage, and gate arithmetic against scenario detail;
- `passed` consistency with each operator, threshold, and actual value;
- `overall_passed` consistency with required gates;
- every implication required for `portfolio_eligible=true`;
- failed mode executions use `judgment=indeterminate`, with completion/failure
  fields consistent with outcome/run state;
- a guarded `blocked` result uses the one exact contract-defined safe reply;
- RFC Problem Details `code`, HTTP `status`, `retryable`, and code-specific
  `type` match `docs/contracts/error-codes.yaml`. Human-readable `title` and
  `detail` remain schema-valid but are not compatibility constants, as stated
  by the Stage 0 contract index.

These rules may be implemented as domain services over schema-valid mappings;
Stage 1 does not need to implement the HTTP endpoints that will later use them.

### S1-TEST — minimum evidence

Automated tests must include:

- positive load and validation of all three committed fixtures;
- exact distribution and cumulative role-matrix assertions;
- at least one negative case for every item in `S1-SEM-DATA` and
  `S1-SEM-REPORT`;
- duplicate YAML key rejection and unknown-field rejection;
- deterministic digest and deterministic issue-order checks;
- validation-error minimization checks proving marker/raw fixture values are not
  copied into issue messages;
- direct construction/serialization round trips for the public Stage 1 domain
  aggregates.

Independent testing must start from a recorded commit SHA and must not treat the
development Agent's self-tests as acceptance evidence.

### S1-DOC — handoff documentation

- README must state the real Stage 1 status and exact installation/validation
  commands without claiming API/RAG/model/database readiness.
- Development, independent test, and architecture acceptance records must each
  bind their conclusion to an exact Git state and state limitations.
- Synthetic fixture provenance, versioning, license, and content warning must be
  discoverable from the README or a directly linked data document.

## 3. Explicit non-goals

Stage 1 does not implement or claim:

- any of the six HTTP endpoints;
- retrieval, embedding, vector index, context assembly, generation, or output
  detection;
- SQLite/PostgreSQL persistence or migrations;
- Ollama availability, model digests, or embedding dimensions;
- Docker/Compose;
- executed 62-scenario baseline/guarded results, ASR, protection effectiveness,
  portfolio eligibility, or résumé evidence.

Those remain later-stage work. A deterministic simulator, if introduced for
unit tests, must not appear in fixture acceptance or any integration/evidence
path.

## 4. Architecture decision gate

Stage 1 is accepted only when all requirements `S1-ENV` through `S1-DOC` have
direct evidence, no blocker/high-severity defect remains, the current public
contracts are unchanged or an explicit compatibility decision approves every
change, and the committed/pushed tree matches the accepted evidence.
