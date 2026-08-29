# KQUANT 84-Day Development Progress

Plan source: `KQUANT 84 天持续开发计划.pdf`  
Current audit date: 2026-07-24 (Asia/Shanghai)

## Frozen outcome

The target is a local, single-user US long-only research and manual-decision
system. Longbridge is the primary market-data source, Yahoo is explicitly
labelled reference fallback, and KQUANT has no account, broker, order, options,
crypto, or automated-execution path.

No real-money use is approved by this progress table. The Go/No-Go gate remains
at Days 78-84 and requires all validation, forward-observation, data-integrity,
and manual-risk criteria to pass.

## Progress board

| Planned days | Objective | Status | Evidence / next boundary |
| --- | --- | --- | --- |
| 1 | Repository audit | Complete | `docs/current_system_audit.md` |
| 2 | Personal live MVP definition | Complete | `docs/personal_live_mvp.md`; six-step manual workflow |
| 3 | Freeze main strategy | Complete as specification | `docs/strategy_specification.md` defines `swing_long_v1.1.0` |
| 4 | Market-data contract | Complete as specification | `docs/market_data_contract.md` |
| 5 | Strategy version system | Complete | `strategy_versions`, stable config hash, signal/Journal/backtest bindings |
| 6 | Development toolchain | Complete | `.venv`-aware launcher, `scripts/verify_all.ps1`, frontend lint/test, CI hooks |
| 7 | First-week review | Complete | README and board updated; full suite: `67 passed` (one upstream deprecation warning) |
| 8 | Longbridge provider audit | Partial | `docs/longbridge_provider_audit.md`; code audit complete, credentialed quote/depth/latency smoke still requires rotated local credentials |
| 9 | Unified candle store | Complete | Canonical `market_candles` and source-observation lineage; legacy cache table retained for compatibility |
| 10 | Market clock | Substantially complete | XNYS/DST/early-close implementation and tests exist; keep regression coverage green |
| 11 | Corporate actions | Partial | Conservative split/reverse-split detection and adjustment-mode lineage are stored; authorised action-feed ingestion and validation blocking remain pending. |
| 12 | Point-in-time universe | Partial | Runtime membership snapshots, content hashes, coverage metadata, and survivorship labels are implemented; authorised historical membership import remains pending. |
| 13 | Daily data-quality report | Substantially complete | Versioned machine-readable candle and realtime quality gate, integrity metrics, and hard vetoes are implemented; scheduled daily aggregate reporting remains pending. |
| 14 | Fault injection | Complete | Deterministic timeout, Longbridge-to-Yahoo fallback, future-candle, and SQLite cache-write failure matrix added, with a dedicated local test runner. |
| 15-21 | Strategy stabilization | Partial | Features, risk and veto logic exist; consolidate to canonical profile and add 20 golden scenarios |
| 22-28 | Reproducible backtest engine | Substantially complete | Deterministic replay now includes cash-only portfolio constraints, benchmark references, complete performance metrics, and versioned JSON/Markdown audit fingerprints. Historical membership remains survivorship-limited. |
| 29-35 | Overfit controls and evidence freeze | Substantially complete | Rolling chronological windows, neighbouring-parameter replay, regime/concentration, confidence checks, Evidence Score, and a gated strategy-freeze manifest exist. No canonical version has been frozen for forward observation without a qualifying real validation run. |
| 36-42 | Forward observation and Journal review | Substantially complete | Bounded daily candidate board, manual plan/position calculator, Decision Ledger, manual Journal, error attribution, and weekly review exist. Real prospective evidence remains intentionally unclaimed until it accumulates. |
| 43-49 | Operational reliability | Substantially complete | Schema versioning, idempotent task records, notification plumbing, operational events, verified backup/restore drill, local-first CORS, rate limit, optional token guard, secret scan, and read-only route scan are implemented. PostgreSQL remains a documented migration contract, not an enabled runtime adapter. |
| 50-56 | Workstation UI release candidate | Substantially complete, pending release verification | Today decision workbench, stock decision data, risk/No-Go panel, exception states, responsive/PWA shell, RC checklist, rollback path and release verifier are implemented. A fresh full release command and browser smoke are required for a green RC. |
| 57-63 | Forward test | Framework complete; evidence not started | Frozen-strategy and frozen-universe requirements, exact daily queue snapshots, outcomes, close notes and data incidents are persisted. Fifteen actual market days cannot be manufactured by code. |
| 64-70 | Paper simulation | Framework complete; evidence not started | Cash-only simulation enforces <=0.25% risk, daily-risk and position limits, no averaging and no chasing. It has no broker integration and needs real manual observations. |
| 71-77 | Simulated pilot and Go/No-Go | Gate complete; evidence not started | Strict historical, forward, paper, discipline and security gates produce `NO_GO` until all facts are recorded. |
| 78-84 | Small-capital manual real-money readiness | Deliberately `NO_GO` | Day-84 report and manual-readiness checklist exist, but they do not enable trading. A Go requires 100+ historical samples, positive OOS/cost evidence and 15 real forward days. |

## Current release baseline

- Local branch: `codex/runtime-validation-v3`.
- Baseline commits: `a006d7e` (strategy contracts/version binding) and
  `a5d36d9` (repeatable verification workflow).
- The public default branch is known to be behind this local baseline. It must
  be reconciled through a reviewed release; never treat the remote `main` as
  containing these changes until that happens.

## Immediate sequence

1. Run a credentialed Longbridge provider audit without exposing credentials.
2. Run an explicitly scoped historical validation, inspect the audit,
   robustness report, benchmarks, and Evidence Score, then decide whether a
   strategy may be frozen for forward observation.
3. Use the daily candidate board and Decision Ledger for paper-observed manual
   review; do not infer real-money readiness from historical results.
4. Complete the PostgreSQL adapter/staging parity work before treating the
   production architecture as deployable.

## Continued Work: Days 49-84

- Added local-first security controls: bounded API request rate, optional
  fail-closed API token, restrictive local CORS, response headers, a
  repository secret-pattern scanner, and explicit read-only route audit.
- Added the Today decision workbench and risk centre panel. It renders a
  `NO_TRADE` decision whenever data, operations, AI availability, market
  state, or the production gate is unsuitable; it never upgrades an abnormal
  state into a BUY conclusion.
- Added a responsive PWA shell that caches only static application assets and
  deliberately never caches API market data.
- Added a forward-pilot ledger and a cash-only paper simulation ledger. Both
  bind observations to a frozen strategy and universe, preserve the original
  plan, and enforce no averaging/no chasing/risk limits without broker access.
- Added the strict Day-84 Go/No-Go evaluator, manual readiness checklist and
  launch-report writer. The current truthful decision is `NO_GO` because
  required historical and prospective evidence has not yet accumulated.

## Evidence Boundary

Days 58-84 include calendar-time work: at least 15 completed market days,
human-recorded outcomes and paper observations. KQUANT can prepare, capture
and evaluate that evidence, but no implementation may backfill it, mark it
complete, or authorize real money. Until the gates turn `GO` from genuine
records, keep the system in paper-observed/manual-decision mode.
