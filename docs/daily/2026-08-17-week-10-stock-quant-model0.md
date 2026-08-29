# KQUANT v2 Week 10 Report: Stock Quant Model 0

Date: 2026-08-17
Branch: `codex/kquant-v2-gap-analysis`
Scope: Stock Quant Dataset and unified strategy kernel

## 1. Goal and completion

Week 10 implementation completion: 100%.

Completed:

- Frozen the first read-only Stock Quant Model 0 contract.
- Added one pure point-in-time feature builder for live analysis and historical replay.
- Added one forward-label builder with next-bar-open execution, costs, gaps, and stop-first handling.
- Added immutable stock quant run, feature snapshot, and label audit tables.
- Added read-only status, ranking, and symbol-detail APIs and CLI commands.
- Added future-data, execution, migration, persistence, and API regression tests.

## 2. Changed modules, schema, API, and UI

Code:

- `kquant/stock_quant.py`: Model 0 feature definitions, point-in-time feature snapshots, labels, dataset sealing, and read-only queries.
- `kquant/stock_signals.py`: attaches the same Model 0 feature snapshot to live scans, single-stock analysis, and historical reconstruction. Forming bars are excluded from the Model 0 input.
- `kquant/__main__.py`: adds `build-stock-quant-dataset` and `stock-quant-status`.
- `kquant/dashboard/app.py`: adds read-only `/api/quant/stocks`, `/api/quant/stocks/ranking`, and `/api/quant/stocks/{symbol}`. Health now reports `stock_quant_model_version`.
- `kquant/db/migrations.py`: adds schema migration v10.

Schema v10:

- `stock_quant_runs`
- `stock_quant_feature_snapshots`
- `stock_quant_labels`

The generic sealed dataset tables remain the source for split integrity and test-partition immutability. The stock-specific tables preserve the full feature and realized-label audit envelope.

The frontend has no new trading control and no order path was added. The existing research UI continues to consume Longbridge live data and remains read-only.

## 3. Data coverage and quality

Current cached coverage report:

- Universe: 296 symbols.
- Longbridge daily eligible: 293/296, 98.99%, target met.
- Longbridge 1H eligible: 294/296, 99.32%, target met.
- Longbridge 1m eligible: 3/296, 1.01%; 1m is not required for the Week 10 Model 0 dataset.
- Canonical validation eligible symbols: 293.
- Market breadth: 294 Longbridge symbols, but the report still identifies the series as incomplete relative to the 296-symbol universe.
- Corporate event calendar: not ingested; it remains a data-quality limitation and is not presented as evidence of strategy performance.
- Yahoo observations remain reference/legacy data and are not eligible for the Model 0 dataset.

Live smoke for RKLB confirmed both daily and 1H candles were returned as `longbridge_candles`. The Model 0 snapshot was present in `/api/stocks/analyze` and carried a stable hash.

## 4. Tests, build, and browser acceptance

Passed:

- Python: `192 passed`.
- New Model 0 and migration/API tests: `22 passed` in the focused run, then included in the full suite.
- Frontend: `npm.cmd test -- --run`, `2 passed`.
- Frontend: `npm.cmd run build`, passed. Vite emitted the existing large-chunk warning.
- Read-only boundary: passed, 94 registered routes, no forbidden order/account/broker routes.
- `git diff --check`: passed.
- Browser: desktop and mobile snapshots loaded, Deep Research drawer remained available, console errors were zero.
- Runtime: `http://127.0.0.1:8001/` restarted successfully; `/api/health` reports schema 10 and Model 0 v1.0.0.

## 5. Technical debt and leakage risks found

- The current live signal response still contains legacy `historical_edge` descriptive summaries. Model 0 does not import or use them, but later UI work must keep the labels visibly separate.
- Corporate event data is not ingested. Model 0 records missing event factors; a future production dataset must decide whether this is an exclusion or a separate evidence stratum before model fitting.
- Current market breadth is useful but not yet a full 296-symbol point-in-time series.
- The existing live strategy and Model 0 output now share a feature entry point, but the legacy action decision itself is not yet replaced by Model 0. Week 11 must compare them before any change in displayed action.
- The historical label builder correctly rejects an entry that opens below its stop as an invalid trade plan; it does not invent a stop fill for a position that could not have been validly entered.

## 6. Model and strategy evidence

No new performance claim is made this week.

- No production Stock Quant dataset has been materialized from the active historical universe.
- No train/validation/test model comparison was run for Model 0.
- No test-set trade count, win rate, Profit Factor, average R, or maximum drawdown is reported.
- No forward observation or paper result is mixed into this contract.
- The existing strategy-validation and legacy historical-edge numbers remain separate descriptive evidence; they are not Model 0 performance.

## 7. Go/No-Go

Implementation Gate: **GO**.

- The kernel, schema, API, migration, future-data tests, execution tests, and regression suite are complete.
- The live/replay feature hash is reproducible for the same point-in-time input.

Research/OOS Gate: **NO-GO**.

- No completed Model 0 OOS evidence exists yet.
- Event-calendar coverage is incomplete.
- No 100-trade test-set gate, cost gate, concentration gate, or 20-day shadow evidence exists.

Operational status remains read-only research and `NO_GO`. Nothing in Week 10 enables a broker, account, order, option, or automatic execution path.

## 8. Branch, commit, and rollback point

- Working branch: `codex/kquant-v2-gap-analysis`.
- Rollback point before Week 10: `0dcee0f` (Week 9 Leadership Engine).
- Week 10 changes are intentionally isolated to the Model 0 kernel, v10 schema, adapters, interfaces, and tests.
- SQLite migration rollback remains verified-backup restore; no destructive migration was used.

## 9. Week 11 plan and blockers

Next week will build the Stock Quant dataset from eligible Longbridge history and run the first Model 0 versus Logistic/LightGBM/Quantile validation comparison. It will preserve date-based rolling splits, purge, embargo, train-only selection, and a permanently read-only test partition.

Blockers:

- Corporate event calendar ingestion must be completed or explicitly excluded as a stratified missing-data condition.
- At least 100 completed test-set trades are required before any OOS conclusion.
- No model may change the current action or unlock live execution before the OOS and shadow gates pass.
