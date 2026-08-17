# KQUANT v2 Week 8 Report: Theme Prediction v1

Date: 2026-08-17  
Branch: `codex/kquant-v2-gap-analysis`  
Scope: Versioned Theme Prediction dataset, label contract, model comparison, validation-only calibration, and fail-closed probability display. No Options Engine, broker, account, position, or order work was added.

## 1. Goal And Completion

**Implementation completion: 100% for the Week 8 code and contract scope.**

Delivered:

- direction, excess-return, rank-percentile, and five-quantile theme labels;
- versioned theme prediction datasets built on the Week 7 sealed PIT dataset contract;
- Naive, Capital Rotation rule, and Logistic comparison models;
- optional LightGBM classifier, regressor, and quantile adapters with explicit `not_installed` status;
- AUC, Brier, ECE, Rank IC, top-decile excess, error, and bootstrap interval diagnostics;
- Platt and Isotonic calibration fitted from validation predictions only;
- three-OOS-fold calibration Gate and product probability fail-closed behavior;
- read-only prediction run APIs, CLI commands, Settings-page evidence card, and regression tests.

## 2. Modules, Schema, API, And CLI

Added `kquant/theme_prediction.py` with:

- strict theme label normalization and PIT availability checks;
- `build_theme_prediction_dataset()`;
- deterministic model comparison and metrics;
- optional LightGBM adapters without making the core runtime depend on LightGBM;
- validation-only Platt and Isotonic calibration;
- `run_theme_prediction()`, `latest_theme_prediction()`, and `theme_prediction_detail()`.

Schema migration v8 adds:

- `theme_prediction_runs`
- `theme_prediction_metrics`
- `theme_prediction_calibrations`

New read-only interfaces:

- `GET /api/models/theme-prediction/latest`
- `GET /api/models/theme-prediction/{run_id}`

New CLI commands:

- `build-theme-prediction-dataset`
- `run-theme-prediction`
- `theme-prediction-status`

The Settings page now shows Theme Prediction evidence, observed versus required OOS folds, and whether probability display is blocked.

## 3. Data And Migration

The active database is `work/kquant_us.sqlite3`.

- Pre-v8 SQLite backup: verified.
- Restore drill: passed; active database was not overwritten.
- Active schema: v8.
- Schema fingerprint after migration: `6bd4dc95a02c231c11d6c1c7d218109fbf064c7afd3f16ec57b58144a75f1a61`.
- Longbridge remains the primary market-data source; the new prediction layer does not enable Yahoo data for eligible modeling.
- No production Theme Prediction dataset was materialized. The active database currently reports `not_materialized`, because one Capital Rotation snapshot is not a valid multi-fold historical prediction dataset.

## 4. Verification

- Python: `183 passed`; one existing Starlette deprecation warning remains.
- Frontend: `npm.cmd test -- --run`, 2 passed.
- Frontend: `npm.cmd run build`, passed; existing 530 kB chunk warning remains.
- Read-only boundary: passed; 89 registered routes, no forbidden trade routes.
- `git diff --check`: passed.
- Live health: API contract `kquant-api-2026-08-17-theme-prediction-v1`, database schema v8, Longbridge configured, persistent quote context active, account/trade/order flags false.
- Browser smoke: Settings displays the Theme Prediction evidence card; Deep Research rail remains available; current Longbridge status is visible.

## 5. Leakage Controls And Remaining Risks

- Theme features must be available no later than signal time.
- Future excess returns are stored only as labels and never enter feature fitting.
- Label direction, excess return, rank percentile, and quantile are versioned and content-hashed.
- Dataset and test partition hashes remain enforced by the Week 7 contract.
- Logistic normalization is fitted from train rows only.
- Platt and Isotonic calibration consume validation predictions and labels only; test rows are evaluated after calibration parameters are frozen.
- LightGBM is optional. If the dependency is absent, its three model slots report `not_installed` instead of fabricating results.
- One three-way split is not three OOS folds. The calibration Gate therefore remains blocked.
- The current implementation does not claim AUC, Brier, win rate, average R, Profit Factor, or drawdown for the live universe.

## 6. Model And Strategy Result

No real Theme Prediction performance result was generated this week. Synthetic fixtures prove label normalization, calibration separation, model registration, integrity failure, and Gate behavior only. They are not historical, OOS, forward, Paper, or live evidence.

The product deliberately returns `display_probability=false` until the dataset contains at least three independent OOS folds and the calibration thresholds are evaluated without test-set tuning.

## 7. Go / No-Go

**Week 8 Gate: PASS for infrastructure; NO-GO for prediction display and real-money use.**

- Versioned label contract: PASS
- Train/validation/test model separation: PASS
- Validation-only calibration: PASS
- Probability display calibration Gate: BLOCKED; observed 1 OOS fold, required 3
- AUC lower bound above 0.5: NOT EVALUATED
- Brier improvement versus climatology: NOT EVALUATED
- ECE <= 0.05: NOT EVALUATED on eligible production data
- Real-money readiness: NO-GO

## 8. Rollback Point And Next Week

Rollback point: Week 8 commit containing the v8 migration and Theme Prediction module. Database rollback is the verified pre-v8 SQLite backup, not a destructive reverse migration.

Week 9 will build the Leadership Engine: point-in-time stock-versus-theme and stock-versus-market relative strength, volume confirmation, persistence, Leader/Emerging/Neutral/Weakening states, and OOS concentration checks. It will consume Theme Prediction only as a versioned evidence input and may not use future predictions to rank historical leaders.
