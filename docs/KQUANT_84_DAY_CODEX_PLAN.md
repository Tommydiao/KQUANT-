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
| 43-49 | Operational reliability | Partial | Local schema versioning, idempotent task records, web/optional personal notification plumbing, structured operational events, verified SQLite backup, and restore drill exist. PostgreSQL is a documented migration contract, not an enabled runtime adapter. |
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

1. Run a credentialed Longbridge provider audit without exposing credentials.
2. Run an explicitly scoped historical validation, inspect the audit,
   robustness report, benchmarks, and Evidence Score, then decide whether a
   strategy may be frozen for forward observation.
3. Use the daily candidate board and Decision Ledger for paper-observed manual
   review; do not infer real-money readiness from historical results.
4. Complete the PostgreSQL adapter/staging parity work before treating the
   production architecture as deployable.
