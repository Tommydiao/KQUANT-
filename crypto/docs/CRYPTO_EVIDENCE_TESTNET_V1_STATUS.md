# Crypto Evidence and Testnet V1 Status

As of 2026-09-04, KQUANT Crypto remains `NO_GO`. This document records the
first implementation checkpoint on `codex/crypto-evidence-testnet-v1`.

## Completed in this checkpoint

- Binance Spot public REST and WebSocket market data use the official
  market-data-only endpoint family. Account and order clients remain separate.
- The market scanner is operational against the public endpoint and fails
  closed on restricted, stale or unavailable providers.
- Stable-asset pairs, leveraged tokens, young listings and incomplete trading
  rules are excluded from scanner promotion.
- ZEC and PUMP are included in the configured Spot research set. HYPE remains
  a perpetual-only candidate with separate derivative requirements.
- `crypto_spot_momentum_v2.1.0` is an immutable challenger. Live analysis and
  historical replay call the same bounded factor scorer.
- Point-in-time Bayesian and deterministic 5,000-path Monte Carlo evidence can
  be attached to a plan. Missing trained Logistic/Quantile artifacts and model
  calibration remain explicit blockers.
- Data coverage now reports a per-symbol 1H/5m matrix based on immutable closed
  K-line snapshots.
- Execution preflight and Testnet readiness endpoints are read-only and cannot
  Arm the controller or submit an order.

## First locked v2.1 validation

Run: `validation_8a6718e3cd07455fa8631fe6307bf018`

Scope: BTCUSDT, ETHUSDT and SOLUSDT Spot long, 1H OHLCV evidence, standard Spot
costs, doubled-cost stress scenario, three locked OOS folds.

| Metric | Locked test result | Required | Status |
| --- | ---: | ---: | --- |
| Completed test trades | 15 | 200 | Fail |
| Expected R | -0.138R | positive CI lower bound | Fail |
| Bootstrap 95% interval | -0.685R to 0.494R | lower bound > 0 | Fail |
| Profit Factor | 0.785 | >= 1.25 | Fail |
| Stress Profit Factor | 0.680 | >= 1.05 | Fail |
| Average win/loss ratio | 1.178 | >= 1.5 | Fail |
| Maximum drawdown | 5.097R | <= 10R | Pass |
| Best asset removed Expected R | -0.560R | > 0 | Fail |

The result is `NO_GO`. The locked test partition must not be used to retune
v2.1. A later strategy version must select parameters on train/validation and
be evaluated on a fresh, untouched test partition.

## Outstanding gates

1. Complete the 1H and 5m archive backfill for at least 90% of the Spot research
   Universe and 99% for BTC/ETH/SOL.
2. Collect an independent 24-hour public market-data session.
3. Produce a new challenger using train/validation only and pass every locked
   OOS performance Gate.
4. Train and register Logistic/Quantile artifacts, then pass calibration and
   model integrity checks.
5. Run the complete Candidate to Plan to EVAL to Shadow chain without duplicate
   state transitions.
6. Configure Binance Spot Testnet credentials and pass read-only account,
   trading-rule, User Data Stream and reconciliation preflight.
7. Only after all earlier gates pass, complete at least 14 calendar days and 30
   closed Testnet trades with zero duplicate orders, unprotected positions,
   risk breaches or reconciliation differences.

No Live credential, Live Arm or real-money order belongs to this checkpoint.
