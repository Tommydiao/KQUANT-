# Week 3 Progress Report: Realtime Buffer and Historical Storage

## 1. Goal and completion

The realtime storage layer is implemented without changing the read-only
boundary. Provider events now pass through clock calibration, bounded in-memory
buffers, closed-candle aggregation and append-only Parquet partitions. The
24-hour runtime Gate remains open and is being collected separately.

## 2. Code and API

- `market_buffer.py`: bounded ring buffers, forming/closed separation, 1m to
  5m/15m/1H/4H/1D aggregation, BBO, spread, order flow and CVD summary.
- `parquet_store.py`: `venue/market_type/symbol/date` partitions and DuckDB
  query/coverage metrics.
- `market_runtime.py`: provider callback, batching and snapshots.
- `clock_sync.py`: public provider server-time calibration for Binance, OKX
  and Kraken. Raw local receipt time remains auditable.
- `GET /api/crypto/data/coverage` and
  `GET /api/crypto/assets/{asset_id}/market-snapshot`.
- `scripts/run_crypto_collection.py`: bounded public-only collection command.
- `scripts/check_crypto_collection.py`: duration and coverage inspection.

## 3. Runtime evidence

The short real collection created 16,063 events across BTC, ETH and SOL for
Binance Spot plus OKX Spot/Perpetual. The machine clock was approximately five
minutes behind provider time; this is now calibrated and recorded rather than
silently accepted. A failed calibration or explicit clock skew remains
untrusted for downstream EVAL.

## 4. Tests and risks

- Python: `26 passed`.
- Forming bars never enter closed history.
- Incomplete higher-timeframe bars are not aggregated.
- DuckDB reads back Parquet partitions.
- Provider sequence gaps require explicit previous-sequence evidence; normal
  provider jumps are not falsely treated as gaps.
- Parquet writes now use a cross-process writer lock and atomic temporary-file
  replacement; coverage/query reads use the same lock.
- Read-only boundary and frontend build remain required before commit.

The remaining risk is long-duration reconnect, storage growth and provider
freshness distribution. A concurrent server/collector smoke test exposed three
partial Parquet files; they were removed after full-column validation and the
writer boundary was fixed. No signal, Paper or Shadow result is generated from
this collection.

**Gate: NO-GO until the 24-hour core-symbol collection is complete and its
coverage, gaps, latency and storage metrics are reviewed.**
