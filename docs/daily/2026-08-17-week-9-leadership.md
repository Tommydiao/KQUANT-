# KQUANT v2 Week 9 Report: Leadership Engine

Date: 2026-08-17  
Branch: `codex/kquant-v2-gap-analysis`  
Scope: Same-timestamp stock leadership relative to theme and market. No Options Engine, broker, account, position, or order work was added.

## 1. Goal And Completion

**Implementation completion: 100% for the Week 9 Leadership Engine scope.**

Delivered:

- point-in-time stock-versus-theme relative strength;
- stock-versus-market relative strength inherited from the Longbridge Capital Rotation snapshot;
- volume confirmation and persistence scoring;
- `Leader`, `Emerging`, `Neutral`, and `Weakening` states with rank explanations;
- theme-size, volatility-proxy, and data-quality strata;
- concentration diagnostics and explicit no-future-prediction metadata;
- read-only Leadership APIs, CLI commands, Settings-page summary, and regression tests.

## 2. Modules, Schema, API, And CLI

Added `kquant/leadership.py` with:

- deterministic `run_leadership()`;
- `latest_leadership()` and `theme_leaders()` read paths;
- score components for theme-relative strength, market-relative strength, volume, and persistence;
- volatility proxy bucket retained as a diagnostic, not a volatility model;
- state transition thresholds kept in the versioned `leadership_engine_v1.0.0` contract.

Schema migration v9 adds:

- `leadership_runs`
- `leadership_scores`

New read-only interfaces:

- `GET /api/leadership/latest`
- `GET /api/themes/{id}/leaders`

New CLI commands:

- `run-leadership`
- `leadership-status`

Settings now displays unique symbols, theme memberships, state counts, timestamp, and whether future theme prediction was used.

## 3. Current Longbridge Snapshot

The active database is `work/kquant_us.sqlite3`.

- Active schema: v9.
- Leadership run: `ldr_fab322f00b8eabcbc0fd`.
- Rotation input: `crr_55d1fd72889dc574b364`.
- Taxonomy input: `ttr_da00cfeaa4857b77194c`.
- Cross-sectional as-of: `2026-08-17T15:03:39.218747+00:00`.
- Source: `longbridge_candles`.
- Unique symbols: 292.
- Theme membership rows: 483 across 17 themes; a symbol may belong to more than one theme.
- States: 97 Leader, 73 Emerging, 106 Neutral, 207 Weakening.
- Maximum theme-member weight: 10%.
- Future data and future Theme Prediction: both false.

This is a descriptive current snapshot, not a forecast or OOS portfolio result. State counts must not be interpreted as win rate.

## 4. Verification

- Python: `186 passed`; one existing Starlette deprecation warning remains.
- Frontend: `npm.cmd test -- --run`, 2 passed.
- Frontend: `npm.cmd run build`, passed; existing 531 kB chunk warning remains.
- Read-only boundary: passed; 91 registered routes, no forbidden trade routes.
- `git diff --check`: passed.
- Backup before v9 migration: verified.
- Restore drill: passed; active database was not overwritten.
- Live health: API contract `kquant-api-2026-08-17-leadership-v1`, schema v9, Longbridge persistent context active, account/trade/order flags false.
- Browser/API smoke: `/api/leadership/latest` and `/api/themes/theme.ai_infrastructure/leaders` return the materialized read-only snapshot.

## 5. Leakage Controls And Remaining Risks

- Leadership consumes the sealed Capital Rotation run's `as_of_time`, taxonomy run, member features, and Longbridge source metadata.
- It does not read the Theme Prediction output, future returns, or current ad hoc tags.
- Future candle insertion after the rotation cutoff does not change the leadership content hash.
- Every member feature carries the rotation cross-sectional timestamp and source marker.
- Theme membership overlap means membership rows exceed unique symbols; concentration diagnostics must be interpreted per theme.
- `high_proxy` is based on recent return/acceleration magnitude, not a validated ATR or realized-volatility measure. It is a stratification diagnostic only.
- No OOS Leader portfolio, Rank IC, cost-adjusted return, or concentration-profit test has been claimed yet.

## 6. Model And Strategy Result

No predictive performance result was generated this week. Leadership ranking is a deterministic evidence layer for later Stock Quant work. The current `Leader` label means relative strength and confirmation are strong in this snapshot; it does not mean “buy” or imply a future return.

## 7. Go / No-Go

**Week 9 Gate: PASS for same-timestamp leadership infrastructure; NO-GO for predictive use and real-money use.**

- Same cross-sectional timestamp: PASS
- Future Theme Prediction excluded: PASS
- Relative strength and confirmation fields persisted: PASS
- Theme-size and volatility-proxy strata: PASS
- OOS Leader portfolio versus theme equal weight: NOT EVALUATED
- Positive Rank IC across multiple folds: NOT EVALUATED
- Real-money readiness: NO-GO

## 8. Rollback Point And Next Week

Rollback point: Week 9 commit containing the v9 migration and Leadership Engine. Database rollback is the verified pre-v9 SQLite backup, not a destructive reverse migration.

Week 10 will freeze Model 0 and build the Stock Quant Dataset plus one pure-function strategy kernel shared by realtime analysis and replay. It will define forward return, run-up, drawdown, realized-R, target/stop labels, next-tradable-bar entry, and stop-first same-bar handling.
