# KQUANT 84-Day Development Progress

Plan source: `KQUANT 84 天持续开发计划.pdf`  
Current audit date: 2026-07-23 (Asia/Shanghai)

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
| 3 | Freeze main strategy | Complete as specification | `docs/strategy_specification.md` defines `swing_long_v1.0.0` |
| 4 | Market-data contract | Complete as specification | `docs/market_data_contract.md` |
| 5 | Strategy version system | Complete | `strategy_versions`, stable config hash, signal/Journal/backtest bindings |
| 6 | Development toolchain | Complete | `.venv`-aware launcher, `scripts/verify_all.ps1`, frontend lint/test, CI hooks |
| 7 | First-week review | Complete | README and board updated; full suite: `67 passed` (one upstream deprecation warning) |
| 8 | Longbridge provider audit | Partial | `docs/longbridge_provider_audit.md`; code audit complete, credentialed quote/depth/latency smoke still requires rotated local credentials |
| 9 | Unified candle store | Complete | Canonical `market_candles` and source-observation lineage; legacy cache table retained for compatibility |
| 10 | Market clock | Substantially complete | XNYS/DST/early-close implementation and tests exist; keep regression coverage green |
| 11 | Corporate actions | Partial | Conservative split/reverse-split detection and adjustment-mode lineage are stored; authorised action-feed ingestion and validation blocking remain pending. |
| 12 | Point-in-time universe | Not started | Store membership history and label survivorship limits |
| 13 | Daily data-quality report | Partial | Health reports exist; formal contract metrics and report version are pending |
| 14 | Fault injection | Partial | Fallback/stale tests exist; complete timeout/future-bar/database failure matrix |
| 15-21 | Strategy stabilization | Partial | Features, risk and veto logic exist; consolidate to canonical profile and add 20 golden scenarios |
| 22-28 | Reproducible backtest engine | Partial | Validation v3 has next-bar/cost/split foundations; canonical `swing_long_v1.0.0` replay, portfolio and benchmark work are pending |
| 29-35 | Overfit controls and evidence freeze | Not started | Walk-forward exists in v3; sensitivity, regime/concentration checks and v1.0.0 freeze remain |
| 36-42 | Forward observation and Journal review | Partial | Journal and prospective outcomes exist; scheduled daily observation/error attribution are pending |
| 43-49 | Operational reliability | Not started | Add migrations, scheduler, notification, backup/restore, structured monitoring |
| 50-56 | Workstation UI release candidate | Not started | Do only after data and strategy evidence are stable |
| 57-63 | Forward test | Not started | Require a fixed strategy/data version and daily observations |
| 64-70 | Paper simulation | Not started | Manual workflow only; no broker integration |
| 71-77 | Simulated pilot and Go/No-Go | Not started | Review safety, drawdown, sample quality and discipline |
| 78-84 | Small-capital manual real-money readiness | Blocked by design | Only after every stated gate passes; KQUANT remains read-only |

## Current release baseline

- Local branch: `codex/runtime-validation-v3`.
- Baseline commits: `a006d7e` (strategy contracts/version binding) and
  `a5d36d9` (repeatable verification workflow).
- The public default branch is known to be behind this local baseline. It must
  be reconciled through a reviewed release; never treat the remote `main` as
  containing these changes until that happens.

## Immediate sequence

1. Complete the Day 7 full verification and repository release reconciliation.
2. Run the Day 8 Longbridge credentialed provider audit without exposing
   credentials.
3. Implement the Day 9 canonical candle schema and Day 11 corporate-action
   policy before using more historical evidence.
4. Do not change any `swing_long_v1.0.0` parameter until the version registry,
   point-in-time universe, and replay path bind to the same immutable version.
