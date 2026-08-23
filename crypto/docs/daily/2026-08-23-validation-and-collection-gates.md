# Validation and collection evidence update

## Scope

This increment makes the two evidence gates explicit and independent:

- `persisted_parquet_span`: data exists in the append-only storage and covers
  the requested symbol/span.
- `independent_collector_session`: one collector process ran for the required
  window, kept core symbols covered and recorded no sequence gaps.

Neither gate opens EVAL, Paper or Shadow permissions.

## Changes

- Added `crypto_validation_gate_v1.0.0`. It reports every locked test/OOS
  requirement with observed value, threshold and failure ID:
  test partition lock, three OOS folds, 200 locked test trades, positive
  bootstrap expected-R lower bound, Profit Factor at least 1.25 and maximum
  drawdown at most 10R.
- Added `GET /api/crypto/validation/gate`. Existing validation reports also
  expose the same gate without writing the database on read.
- Added `crypto_collection_gate_v1.0.0` and collector heartbeat/final-report
  files. `scripts/check_crypto_collection.py` now returns persisted coverage
  separately and keeps the top-level collection gate `NO_GO` until an
  independent collector report passes.
- Closed K-line snapshots are now interval-specific. `1m` remains the live
  hydration snapshot; `15m`, `1h` and other maintenance snapshots are stored
  beside it and cannot overwrite it.

## Actual evidence

- Public Binance `1h` backfill completed for the configured 29-symbol CEX
  universe. The first run added about 5,617 closed hourly rows per symbol
  (BTC was already complete), with no provider errors. These rows are
  historical public market data, not trading evidence.
- All 29 symbols now have native `1h` compacted snapshots. Symbol-filtered
  traversal and merge-safe interval snapshots preserve the existing symbols
  when a bounded batch is compacted; the live `1m` snapshot remains separate.
- The full-universe `1h` replay created run
  `validation_559ad078697c44c59e181707de37ed3f` with 432 locked test trades,
  43.29% win rate, average `+0.115R`, Profit Factor `1.205` and maximum
  drawdown `16.53R`. Its 95% bootstrap expected-R interval is
  `[-0.012R, +0.252R]`; the OOS chain is still below the required evidence
  gate. This is a robust-sized historical sample but not a passing strategy
  result or a live win rate.

## Gate status

- Validation performance: `NO_GO`; the latest run has enough locked test
  trades for the count check, but fails the positive bootstrap lower bound,
  PF `>= 1.25`, and maximum drawdown `<= 10R` checks.
- Persisted coverage: `PASS` for the stored span reported by the coverage
  index.
- Independent continuous collection: `PENDING`; the active 24-hour collector
  is still running and started before the heartbeat patch, so its final report
  is not available yet.
- EVAL, Alert, Paper and Shadow permissions remain closed. No account, wallet,
  private-key or order route was added.

## Verification

- Python: latest full run before this data-only replay was `138 passed`; the
  EVAL release-flag regression subset is `23 passed`.
- The full 30-symbol validation run completed and was persisted without
  changing any order or account capability.
- Frontend: Vitest `1 passed`; Vite production build passed.
- Read-only boundary: passed.
- Local runtime: `/api/health` returned `ok`, Schema `12/12`, read-only true;
  dashboard PID `18288` and collector PID `19480` remained responsive.
