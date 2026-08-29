# Week 2 Progress Report: Public CEX Market Contract

## 1. Goal and completion

The public market-data contract is implemented for Binance Spot, Binance
USDⓈ-M public streams, OKX public channels, Coinbase Advanced Trade public
ticker data and Kraken public ticker data. All adapters normalize events into
the same immutable shape and have no account, wallet or order capability.

Completion is code-complete for the week, but the real-runtime Gate is still
open: the required 24-hour core-symbol collection has not been claimed from a
short smoke test.

## 2. Modules and interfaces

- `kquant_crypto/market_models.py`: normalized event, provider health and
  sequence tracker contracts.
- `kquant_crypto/providers/binance.py`: Spot and perpetual public streams,
  ticker, book ticker, trade, kline and mark price parsing.
- `kquant_crypto/providers/okx.py`: public ticker, books5, trades, candles,
  mark-price and funding-rate parsing.
- `kquant_crypto/providers/coinbase.py`: public ticker subscription and
  normalization.
- `kquant_crypto/providers/kraken.py`: public ticker subscription and
  normalization.
- `kquant_crypto/provider_runtime.py`: isolated reconnect loop, sequence gap
  detection and provider event audit.
- `GET /api/crypto/providers/status`: provider state and core symbols.
- `GET /api/crypto/data/coverage`: honest not-collected status until the
  historical storage layer is implemented.

The dashboard starts the provider supervisor only when a public provider flag
is explicitly enabled. The default remains disabled.

## 3. Verification

- Python: `18 passed`.
- Public WebSocket smoke: Binance, OKX and Coinbase connected and returned a
  message without credentials or write permissions.
- Read-only boundary: passed.
- Frontend test: `1 passed`.
- Frontend production build: passed.
- `git diff --check`: passed for the tracked working changes.

## 4. Risk and Gate

The remaining evidence gap is runtime duration: no 24-hour collection,
reconnect statistics, disk usage or provider freshness distribution exists
yet. Sequence gaps currently fail the provider state to `resync_required`; a
REST snapshot recovery path belongs in the next data-storage increment before
signals can consume the stream.

**Gate: NO-GO for signals, Paper and Shadow.** The implementation may proceed
only as public data collection and test work. No forecast or performance
claim is made.
