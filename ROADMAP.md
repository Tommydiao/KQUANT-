# KQUANT Public Roadmap

This roadmap describes the public, open-source direction of KQUANT. It is intentionally outcome-oriented rather than date-driven. Historical implementation progress remains available in `docs/KQUANT_84_DAY_CODEX_PLAN.md`.

KQUANT will remain **research-only**. The roadmap does not include broker/exchange account access, wallet signing, automated order submission or model-controlled execution.

## Current baseline — v0.2

The current baseline provides:

- separate US equities and crypto research terminals;
- a unified local workspace and health surface;
- read-only market-data/provider integrations;
- deterministic Data Trust and evidence gates;
- transparent factors and reproducible strategy validation;
- advisory AI/LLM research paths that cannot override deterministic gates;
- crypto Paper/Shadow observation workflows without execution authority;
- CI, secret scanning, frontend/backend tests and read-only boundary verification.

## v0.2.x — OSS foundation and reproducibility

Goal: make KQUANT easy to inspect, reproduce and contribute to safely.

Planned work:

- [x] Add an open-source license and contributor/security policies.
- [x] Publish architecture and project-scope documentation.
- [ ] Stabilize a one-command local demo for each terminal.
- [ ] Add issue/PR templates and contributor-focused setup diagnostics.
- [ ] Expand cross-platform setup beyond the current Windows-first workflow.
- [ ] Publish a minimal synthetic/demo dataset path that requires no private credentials.
- [ ] Keep CI green across stocks, crypto and the unified shell.

## v0.3 — Unified Data Trust contract

Goal: make market evidence comparable, inspectable and fail-closed across asset classes.

Planned work:

- [ ] Standardize provider capability metadata across stocks and crypto.
- [ ] Standardize provenance, source time, freshness, closed-bar and missing-data semantics.
- [ ] Add provider contract tests and deterministic failure fixtures.
- [ ] Improve historical coverage reporting without overstating continuous collection.
- [ ] Add reproducible data-quality reports suitable for issue/PR evidence.

## v0.4 — Evaluation and strategy research framework

Goal: make research claims reproducible and resistant to leakage and overfitting.

Planned work:

- [ ] Expand golden/synthetic evaluation datasets.
- [ ] Strengthen point-in-time universe and corporate-action handling.
- [ ] Publish deterministic benchmark examples for validation and rolling OOS workflows.
- [ ] Add standardized cost, slippage and sensitivity reports.
- [ ] Separate historical model benchmarks from prospective observations in all public reports.

## v0.5 — Advisory AI research layer

Goal: explore useful agentic research workflows without transferring decision authority to an LLM.

Planned work:

- [ ] Define a public schema for AI research/advisory outputs.
- [ ] Add regression evals for explanations, evidence citations and structured outputs.
- [ ] Add failure tests for prompt/tool paths that attempt to bypass deterministic gates.
- [ ] Improve traceability between data snapshots, factors, strategy versions, model outputs and EVAL decisions.
- [ ] Publish examples showing how an LLM can assist research while remaining non-authoritative.

## v0.6 — Operations, observability and packaging

Goal: make long-running local research easier to operate and diagnose.

Planned work:

- [ ] Improve runtime supervision and health diagnostics.
- [ ] Add clearer provider-latency, stale-data and collection-status observability.
- [ ] Harden backup/restore and schema-migration verification.
- [ ] Reduce setup friction and package common workflows behind stable CLI commands.
- [ ] Document a production-like self-hosting architecture while retaining research-only permissions.

## Long-term research directions

Potential directions, subject to evidence and contributor interest:

- richer cross-asset regime research;
- portfolio-level research constraints and risk attribution;
- more transparent factor/model comparison tooling;
- public benchmark datasets and evaluation harnesses;
- better human-in-the-loop research review;
- agent-assisted maintenance, testing, documentation and data-quality investigation.

## Explicit non-goals

KQUANT does **not** plan to become:

- an automated trading bot;
- a broker/exchange execution client;
- a wallet or private-key manager;
- a source of guaranteed returns or investment recommendations;
- a system where an LLM can bypass deterministic safety/evidence gates.

## How to contribute

Roadmap items are intentionally broad. Before implementing a large item, open an issue describing the problem, expected evidence, affected safety boundaries and a proposed acceptance test. See [CONTRIBUTING.md](CONTRIBUTING.md).
