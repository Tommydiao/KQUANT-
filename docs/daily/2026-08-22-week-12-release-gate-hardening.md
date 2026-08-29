# KQUANT v2 Week 12: Release Gate Hardening

Date: 2026-08-22
Branch: `codex/kquant-v2-gap-analysis`
Scope: read-only research, validation governance, and Shadow Observation
prerequisites. No broker, account, position, order, or execution capability was
added.

## 1. Goal and completion

Goal: make the Phase 5 release decision use the immutable Stock Quant evidence
chain rather than legacy descriptive labels, and prevent a generic strategy
freeze from starting Shadow Observation.

Implementation completion: 100%.

Research / Shadow gate: NO_GO.

## 2. Delivered modules

- `kquant/stock_quant_validation.py`
  - Advanced the immutable validation schema to
    `stock_quant_validation_v1.2.0`.
  - Added final deployment gates for conservative-cost Profit Factor, removing
    the best five symbols, single-symbol profit concentration, and calibrated
  and single-symbol profit concentration.
- Stores calibration comparison after selection as a diagnostic. It cannot
  select a model or block a passing Model 0 baseline, which preserves the
  approved rule that an unstable model gain falls back to the simpler model.
- `kquant/strategy_freeze.py`
  - Adds `freeze_stock_quant_strategy_for_shadow()`.
  - A Shadow freeze now records the validation run id, validation version,
    deployment model, and immutable validation content hash.
- `kquant/forward_pilot.py` and `kquant/shadow_observation.py`
  - Add `shadow_start_readiness()`.
  - A session may be prepared or activated only when a frozen manifest matches
    an eligible, verified Stock Quant validation run with every Phase 5 check
    passing.
- `kquant/production_readiness.py`
  - Replaces legacy historical-label gates with verified Stock Quant Phase 5
    evidence.
  - Legacy descriptive label statistics remain visible for audit only and are
    explicitly not a production Gate.
- `web/src/components/QuantOverviewPanel.tsx`
  - Adds readable Chinese and English labels for the new deployment blockers.
- `kquant/dashboard/app.py`, `start_kquant_stock_terminal.ps1`, and
  `web/src/App.tsx`
  - Align the backend, startup self-check, and frontend API contract at
    `kquant-api-2026-08-22-v2-oos-shadow-v2`, so a healthy current service is
    not incorrectly labelled as needing a restart.

No database migration was needed. Existing immutable JSON reports in the v11
validation tables carry the new versioned report schema.

## 3. Data and validation result

The latest validation run is `sqv_9c5bc37cecb0e9474a4d77fb` over the existing
Longbridge-only dataset `stock-model0-lb-validation-100-v2`.

- Validation version: `stock_quant_validation_v1.2.1`.
- Dataset integrity: verified.
- Model selected using train and validation only: `logistic`.
- Deployable model: none.
- Deployment status: `no_eligible_model`.
- Selected sealed-test trades: 25.
- Failed deployment checks:
  - `minimum_test_trades`
  - `walk_forward_stability`
  - `single_symbol_profit_contribution_at_most_15pct`

These are historical research diagnostics. They are not a live win rate,
investment recommendation, or execution result.

## 4. Tests and browser acceptance

- Focused safety, validation, and workbench tests: `32 passed`.
- Full Python regression: `208 passed in 249.34s`.
- Frontend unit tests: `2 passed`.
- TypeScript and Vite production build: passed. The existing single JavaScript
  chunk remains above 500 kB and emits a non-blocking build warning.
- Read-only boundary scan: passed with 99 registered routes and no broker,
  account, position, or order-submission route.
- Browser smoke: the current local service displayed `No deployable model`, 25
  test trades, and all four current blockers. Desktop and 375px mobile layouts
  had no horizontal overflow, and the browser console had zero errors.
- Added coverage for:
  - Stock Quant freeze rejection without an eligible immutable validation.
  - Manifest-to-validation hash linkage.
  - Generic freeze blocking forward preparation.
  - Hash mismatch blocking Shadow Observation.
  - Phase 5 readiness ignoring legacy descriptive statistics.
  - Backend, frontend, and startup-script API contract alignment.
- `git diff --check` passed before commit.

## 5. Leakage and technical-debt register

- Calibration comparison uses the sealed test partition only as a diagnostic.
  It must never feed model selection or parameter tuning.
- The short available historical range and only 25 selected sealed-test trades
  are insufficient to establish broad robustness.
- Corporate-action and event-risk coverage remain incomplete and must continue
  to be tracked outside legacy label statistics.
- A passing historical report still cannot replace genuine 20-trading-day
  Shadow Observation or prospective outcomes.

## 6. Go / No-Go

- Go: immutable validation linkage, fail-closed Shadow start, and removal of
  legacy-label release authority.
- No-Go: no Shadow session, no execution interpretation, and no change to the
  read-only research boundary.

## 7. Rollback and next work

Rollback point before this slice: `f53f7b4`.

This slice receives its own commit after the recorded verification suite. The
next work is data accumulation and evidence expansion: widen the
eligible validation sample without changing the sealed strategy through
uncontrolled tuning, then rerun the immutable validation. Shadow Observation
remains blocked until every Phase 5 check passes.
