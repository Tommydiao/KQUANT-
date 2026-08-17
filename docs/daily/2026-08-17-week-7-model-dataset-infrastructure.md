# KQUANT v2 Week 7 Report: Model And Dataset Infrastructure

Date: 2026-08-17  
Branch: `codex/kquant-v2-gap-analysis`  
Scope: Dataset Builder, point-in-time split contract, sealed test partitions, and read-only baseline model artifacts. No Options Engine, broker, account, position, or order work was added.

## 1. Goal And Completion

**Implementation completion: 100% for the Week 7 infrastructure scope.**

Delivered:

- explicit dataset, partition, item, model artifact, and model metric tables;
- feature and label schema versions stored with every dataset;
- date-based 60/20/20 rolling split with label-overlap purge and holding-period embargo;
- immutable dataset and sealed test-partition hashes;
- train-only Logistic fitting plus Naive and Capital Rotation rule baselines;
- model artifact registry with dataset hash, feature order, seed, environment, and test hash;
- read-only model registry APIs and CLI inspection commands;
- fail-closed integrity checks and regression tests.

## 2. Modules, Schema, API, And CLI

Added `kquant/quant_dataset.py` with:

- `rolling_purged_splits()` for whole-date partitioning;
- `build_quant_dataset()` and `read_quant_dataset()` for content-addressed, sealed datasets;
- `run_baseline_suite()` for `naive`, `capital_rotation_rule`, and `logistic` baselines;
- `register_model_artifact()`, `list_model_artifacts()`, and `model_artifact_detail()`;
- strict UTC timestamps, feature availability checks, finite numeric checks, and test-hash verification.

Schema migration v7 adds:

- `quant_datasets`
- `quant_dataset_partitions`
- `quant_dataset_items`
- `quant_model_artifacts`
- `quant_model_metrics`

New read-only interfaces:

- `GET /api/models/validation-runs`
- `GET /api/models/{artifact_id}/metrics`

New CLI commands:

- `build-quant-dataset`
- `quant-dataset-status`
- `run-quant-baselines`
- `quant-model-artifacts`

## 3. Data And Migration

The active database is `work/kquant_us.sqlite3`.

- Pre-migration SQLite backup: verified.
- Restore drill: passed; active database was not overwritten.
- Active schema: v7.
- Schema fingerprint after migration: `ddb274d7cff12475000166176ba19dd00cb43ed9257bd48e8be47c6b9f5098b8`.
- Migration is forward-only; rollback remains verified-backup restore.
- No production quant dataset was materialized from synthetic examples. The test fixtures are only for contract verification.

This distinction is intentional: Week 7 makes the evidence pipeline reproducible, but it does not manufacture a historical strategy result before eligible Longbridge point-in-time rows are assembled.

## 4. Verification

- Python: `179 passed`; one existing Starlette deprecation warning remains.
- Frontend: `npm.cmd test -- --run`, 2 passed.
- Frontend: `npm.cmd run build`, passed; existing 529 kB chunk warning remains.
- Read-only boundary: passed; 87 registered routes, no forbidden trade routes.
- `git diff --check`: passed.
- Live health: API contract `kquant-api-2026-08-17-quant-dataset-v1`, database schema v7, Longbridge configured and running in market-data-only mode.

## 5. Leakage Controls And Remaining Risks

- Features cannot be available after signal time.
- Labels must end after signal time and are checked for overlap with the next partition.
- Splits use whole signal dates, not individual rows, so symbols from one date cannot cross a split boundary.
- Embargo dates are recorded in partition metadata.
- Test partition hashes are stored in both the dataset and each model artifact. Tampering blocks reads and model inspection.
- Logistic normalization is fitted from train rows only.
- Model artifacts record feature order, schema versions, random seed, environment, dataset ID, and test partition hash.
- The current contract treats classification targets as `[0, 1]`; continuous return and realized-R labels belong to the Week 10 stock quant contract.
- The synthetic test suite proves infrastructure behavior only. It is not a performance claim and must not be shown as live or OOS accuracy.

## 6. Model And Strategy Result

No real strategy performance result was generated this week. In particular, there is still no valid statement for live win rate, average R, Profit Factor, or maximum drawdown. The baseline registry is ready to receive eligible point-in-time datasets and deliberately exposes the test partition as evaluation-only.

## 7. Go / No-Go

**Week 7 Gate: PASS for infrastructure; NO-GO for strategy or real-money use.**

- Reproducible split and content hash: PASS
- Future feature availability rejection: PASS
- Test partition tamper detection: PASS
- Train-only baseline fitting: PASS
- Empty, existing, and repeated schema migration: PASS
- OOS performance threshold: NOT EVALUATED
- Real-money readiness: NO-GO

## 8. Rollback Point And Next Week

Rollback point: Week 7 commit containing the v7 migration and dataset contract. Database rollback is the verified pre-v7 SQLite backup, not a destructive reverse migration.

Week 8 will add the versioned Theme Prediction dataset and model comparison layer. It will start with direction, excess-return, ranking, and quantile labels, then add validation-only calibration and reliability diagnostics. No prediction probability will be shown in the product until the OOS calibration Gate passes.
