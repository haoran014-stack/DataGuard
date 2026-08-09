# Synthetic fixture data

`data/synthetic-v1/` contains the three committed-intent inputs for the local
DataGuard experiment: six synthetic identities, thirty short bilingual
documents, and sixty-two scenarios. The files are YAML instances of the JSON
Schemas in `docs/contracts/` and are validated before typed model parsing.

All names, facts, labels, Canary values, protected fragments, and adversarial
instructions are invented for this repository. They contain no real people,
organizations, credentials, customer records, or production text. Some
documents and questions deliberately contain obvious prompt-injection language
for defensive security testing; treat every fixture as untrusted test content.

The fixture text is distributed under the repository MIT License. Third-party
model licenses are separate and do not apply to these authored fixtures.

Committed fixture bytes use UTF-8 without a byte-order mark and LF line
endings. SHA-256 identifiers are computed over those exact bytes without
Unicode or newline normalization.

