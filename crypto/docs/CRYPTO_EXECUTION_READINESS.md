# KQUANT Crypto execution readiness

Generated: 2026-09-02

## Decision

The execution decision is **NO_GO**. Binance Testnet and Live remain locked.

The latest challenger checkpoint and locked metrics are documented in
`CRYPTO_EVIDENCE_TESTNET_V1_STATUS.md`. Its first v2.1 test result is also
`NO_GO`; this file retains the prior strategy runs as immutable history.
The code now contains a gated execution foundation, but no strategy-product-
direction unit has passed the historical performance gate. Live also requires
at least 14 calendar days and 30 closed Testnet trades with clean
reconciliation.

## Historical data baseline

All imported files came from Binance's public market-data archive and were
verified with the archive checksum before ingestion.

| Dataset | Symbols | Interval | Period | Rows |
| --- | --- | --- | --- | ---: |
| Spot closed K-lines | BTCUSDT, ETHUSDT, SOLUSDT | 1h | 2021-01 to 2026-08 | 146,680 |
| USD-M perpetual closed K-lines | BTCUSDT, ETHUSDT, SOLUSDT | 1h | 2021-01 to 2026-08 | 148,848 |
| USD-M funding events | BTCUSDT, ETHUSDT, SOLUSDT | funding interval | 2021-01 to 2026-08 | 18,696 |

Historical open interest is not present in the current dataset. Perpetual
results are therefore explicitly marked `funding_only_limited`; they must not
be described as full derivative-factor validation.

## Locked OOS results

### Spot long

- Run: `validation_f6dc47254492407a911360df1675158a`
- Strategy: `crypto_historical_spot_long_v1.0.0`
- Dataset hash: `c421e50a5c68fd455da5d155378fb07edcea00cbb0f7c209da00ede2abb23d87`
- Test trades: 394
- Win rate: 33.25%
- Average winner / loser: 1.488R / -1.060R
- Realized win/loss ratio: 1.403
- Expected R: -0.213R
- Profit Factor: 0.699
- Maximum drawdown: 84.00R
- Expected-R 95% bootstrap interval: [-0.336R, -0.089R]
- Doubled-cost Profit Factor: 0.496
- Gate: **NO_GO**

### USD-M perpetual long with historical funding

- Run: `validation_820b868fe2e94f27a1f74152a9c1757f`
- Strategy: `crypto_historical_perpetual_funding_long_v1.0.0`
- Test trades: 296
- Win rate: 38.18%
- Average winner / loser: 1.386R / -1.023R
- Realized win/loss ratio: 1.354
- Expected R: -0.104R
- Profit Factor: 0.836
- Maximum drawdown: 37.00R
- Maximum consecutive losses: 9
- Gross average R before costs and funding: 0.063R
- Average trading cost: 0.163R
- Average funding contribution: -0.003R
- Doubled-cost Profit Factor: 0.668
- Gate: **NO_GO**

The current independent perpetual short strategy is not implemented. It is
not permissible to infer short performance by reversing long signals.

## Execution safeguards implemented

- Mode is `disabled` by default, with separate Testnet and Live credentials.
- Process-local manual Arm resets on restart.
- Live capital is capped at 50 USDT.
- Risk per trade, daily loss, and total open risk are each capped at 1%.
- Perpetual leverage is capped at 2x, isolated, one-way mode.
- Entry is limit IOC with maximum-slippage protection.
- Partial fills protect only the filled quantity.
- Spot uses native protection orders; perpetual exits are reduce-only.
- Unknown write responses are reconciled instead of blindly retried.
- Protection failure triggers an emergency exit attempt and Kill Switch.
- One asset cannot be held in both Spot and perpetual form.
- Exchange minimum quantity/notional cannot override risk limits.
- No arbitrary manual order API is exposed.

## Remaining blockers before Testnet

1. Design and freeze an independent perpetual short strategy.
2. Produce a strategy unit that passes every locked OOS and stress-cost gate.
3. Complete protection-order lifecycle and sibling-cancellation tests.
4. Implement Binance User Data Stream consumption and durable reconnect.
5. Reconcile balances, positions, fills, fees, funding, and all order states.
6. Run credentialed Binance Testnet smoke tests without regional restriction bypass.

## Remaining blockers before Live

1. Complete all Testnet blockers.
2. Observe at least 14 calendar days and 30 closed Testnet trades.
3. Complete reconciliation with zero unknown or protection-failed orders.
4. Re-run validation with actual account commission rates.
5. Use a Live API key with withdrawals disabled and an IP allowlist.
6. Explicitly enable Live mode, auto-trading, and process-local manual Arm.

Backtests, Testnet trades, and Shadow observations must never be labelled as
live win rate. No current result supports enabling real-money execution.
