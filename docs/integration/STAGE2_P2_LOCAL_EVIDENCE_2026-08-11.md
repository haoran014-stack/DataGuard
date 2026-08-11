# Stage 2 P2 local integration evidence - 2026-08-11

## Scope and environment

This record distinguishes implemented and developer-checked offline deliverables
from real dependency execution. It contains no simulated integration result and
no claim that security gates passed.

| Probe | Result |
| --- | --- |
| Repository baseline | clean `main@113790dd447999d055f781b69da54e81158cac03` before P2 |
| Python | 3.12.7 |
| Docker CLI / daemon / Compose | **NOT RUN - Docker command absent from PATH** |
| Ollama CLI | **NOT RUN - Ollama command absent from PATH** |
| `http://127.0.0.1:11434/api/version` | **NOT RUN - endpoint unavailable** |
| Ollama tags and fixed models | **NOT RUN - endpoint unavailable; no model pull attempted** |
| PostgreSQL port 5432 | no listening endpoint observed |
| Lock tool initially | `pip-compile` and `uv` absent |
| Lock tool preparation | PyPI index reported pip-tools 7.6.0; installed only into project `.venv` |

## Hashed lock construction and verification

The first `pip-compile` attempt reached its 240-second bound and produced no
partial lock. Platform-specific wheel downloads were then used as the hash trust
source. Linux runtime and development downloads exited 0. The Windows download
reached the same 240-second command bound after pip reported all 33 resolved
wheels saved; the complete set was subsequently proven offline rather than
retrying the network command.

The committed locks have deliberately narrow targets:

- `runtime-linux.lock`: CPython 3.12, `manylinux2014_x86_64`, runtime only.
- `dev-linux.lock`: the Linux runtime lock plus the CPython 3.12 test overlay.
- `dev-windows.lock`: complete runtime and test set for CPython 3.12,
  `win_amd64`.

All three passed offline `pip install --dry-run --ignore-installed
--require-hashes --no-index --only-binary=:all:` resolution against the exact
downloaded wheels (exit 0). Static tests require every non-include line to be an
exact `==` pin with a SHA256 and reject URLs, editable requirements, index
directives, and trusted-host directives. The normal host workflow uses
`PYTHONPATH=src`; it does not run an editable install after the hash-checked
dependency installation.

## Offline deliverables exercised

- Closed configuration including literal, explicit container-host-gateway opt-in.
- Side-effect-free ASGI factory and fixed six-route inventory.
- Explicit fixture validation, real-Ollama index build, strict manifest generation,
  and prepared-artifact verification commands. Network-dependent commands fail
  with minimized output when Ollama is unavailable.
- Docker/Compose static files: API plus PostgreSQL only, host Ollama, non-root API,
  read-only root/artifact mount, dropped capabilities, no-new-privileges, no
  Docker socket, named PostgreSQL volume, and a context exclusion policy for
  local state, secrets, tests, and non-contract documentation.
- PowerShell demonstration with exact model tag preflight, no pulling, both chat
  modes, bounded health/evaluation polling, report/audit retrieval, and
  non-destructive default cleanup.
- P2 targeted tests after final delivery corrections: 64 passed in 23.31 seconds.
- Full developer suite after final delivery corrections: 711 passed in 109.69 seconds.
- Stage 1 validation compatibility: 6 identities, 30 documents, 62 scenarios,
  zero issues; exit 0.
- Product/test compile, PowerShell demo parse, UTF-8/LF, local Markdown links,
  credential heuristic, system-marker uniqueness, and `git diff --check` all
  completed without a delivery defect.

## Real execution not performed

The following are **NOT RUN**, not failures and not passes:

- Docker build and hashed-install smoke inside Linux.
- `docker compose config`, PostgreSQL startup/health, persistence, and restart recovery.
- Real Ollama probe/show/embed/chat and actual local model digest capture.
- Real 30-document vector-index construction and strict evidence manifest.
- Baseline/guarded chat, complete 62-pair evaluation, audit, JSON/HTML report.
- Model-offline and database-outage runtime demonstrations through containers.

Run `scripts/demo.ps1` only after installing these dependencies and reviewing
`.env.example`. The script never pulls models and preserves the named database
volume by default.

Final delivery review replaced the Docker denylist with a minimal allowlist:
only Dockerfile, product source, synthetic data, machine contracts, and the
Linux runtime lock may enter the build context. The demo now treats the two
prepared artifacts as one state pair, rejects a partial pair, reuses a complete
pair, and replaces them only under `-OverwriteArtifacts`. Every HTTP operation
has a fixed timeout and each health loop starts from a fresh null state.
