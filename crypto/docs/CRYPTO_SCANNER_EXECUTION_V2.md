# Crypto Scanner And Execution V2

## Runtime flow

The active backend flow is:

`Binance public market scan -> ranked watch/deep pools -> closed 1H setup -> closed 5m trigger -> trade plan -> EVAL -> execution admission -> account risk -> order manager -> account stream -> reconciliation`

The market scanner refreshes every 15 minutes. It ranks at most 150 eligible
USDT Spot instruments and reserves the first 50 for trade, BBO, and order-flow
monitoring. Futures and cross-source reference providers remain restricted to
the configured core symbols. Only `BTCUSDT`, `ETHUSDT`, and `SOLUSDT` can pass
execution admission.

## Frozen strategy

`crypto_spot_momentum_v2.0.0` is a new frozen research baseline. It uses a
closed 1H setup and a closed 5m trigger. The prior negative-result strategies
remain available for comparison and are not silently retuned.

The v2 strategy has no passing locked OOS report yet. Therefore the current
execution result is `NO_GO`, regardless of source-code completeness.

## Execution boundary

Only `ExecutionOrchestrator` can translate a persisted EVAL result into an
immutable `ExecutionIntent`. Admission requires all of the following:

- `SHADOW_ELIGIBLE` and `allowed_shadow=true` from EVAL.
- A `PASS` validation gate for the exact strategy version.
- An allowlisted symbol and executable strategy manifest.
- A non-expired plan with valid long geometry.
- An armed runtime, configured credentials, account capacity, symbol rules,
  and a passing account-aware risk decision.

Signal, Alert, and LLM components do not hold an Order Manager reference.

## Account events and recovery

The Spot User Data Stream normalizes order and balance events, persists a
deduplicated audit event, updates locally known order state, and records fills.
Stream failure disarms execution before a REST reconciliation attempt. Futures
account streaming remains disabled until its independent long and short
strategies pass validation.

## Remaining external gates

The following cannot be completed by code alone:

- At least 200 locked OOS test trades and all performance thresholds for v2.
- Binance Testnet credentials and permission checks.
- Fourteen natural days and at least 30 closed Testnet trades.
- Zero reconciliation differences, duplicate orders, unprotected fills, and
  risk-limit breaches during that observation window.

Until those gates pass, keep `KQUANT_CRYPTO_EXECUTION_MODE=disabled` and
`KQUANT_CRYPTO_AUTOTRADE_ENABLED=false`.
