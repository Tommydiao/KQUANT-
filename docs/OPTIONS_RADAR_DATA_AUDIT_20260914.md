# KQUANT Options Radar Data Audit

Audit time: 2026-09-14 (Asia/Shanghai)  
Policy: `option_radar_v1.0.0`  
Scope: SPY, QQQ, AAPL, MSFT, NVDA, AMZN, META, GOOGL, TSLA, AMD, AVGO, IWM

## Executive result

The radar engineering path is available, but strict option simulation is blocked by market-data and event-data gaps.

| Contract | Observed result | Consequence |
| --- | --- | --- |
| Longbridge credentials and QuoteContext | Available | Read-only stock and option-chain calls can run |
| US stock realtime package | `US_QBBO_OpenAPI` | Underlying stock BBO is available |
| Option expiry and chain | Available; SPY included the current 0DTE expiry | Contract identity can be selected |
| OPRA realtime option quote | Not detected | No intraday option confirmation or simulated fill |
| Direct option quote probe | `301604 no quote access` | Option price, IV, OI, volume, and Greeks are unavailable from the current entitlement |
| Native BBO event time | Not available from the current path | Request receipt time cannot be substituted for exchange event time |
| Earnings/dividend/macro calendar | 0 of 12 symbols trade-eligible | Plans remain observation-only |
| Historical option bid/ask and adjustments | No stored evidence | No option-strategy win rate, payoff, or Profit Factor can be calculated |
| New radar outcomes | 0 at audit time | Performance is `PERFORMANCE_UNPROVEN` |
| Latest source evidence | 12 underlying snapshots and 12 event snapshots | The full initial universe is now auditable |
| Local clock vs official public server | Local clock was about 335.6 seconds behind in a 1.54 second probe | All affected realtime evidence is blocked; tolerance was not widened |

Longbridge documents the option quote `timestamp` as the latest trade time. It is not evidence of when the bid and ask were formed. The radar therefore stores `latest_trade_time`, `bbo_received_at`, and `bbo_event_time` separately. Receipt-only BBO is rejected for simulated fills.

The clock check compared the midpoint of the local request interval with Binance's public market-data-only `/api/v3/time` endpoint. It confirmed the same approximate five-minute offset seen in the Longbridge premarket timestamp. The radar now records this as a clock-contract conflict whenever a provider event is more than 30 seconds ahead. Strict option evidence additionally requires native BBO event and receipt clocks to agree within 15 seconds. It does not use provider server time to rewrite the local clock, and no service or Windows time setting was changed.

References:

- Longbridge option quote: https://open.longbridge.com/docs/quote/pull/option-quote
- Longbridge option calculation indexes: https://open.longbridge.com/docs/quote/pull/calc-index
- Cboe US options hours: https://www.cboe.com/about/hours/us-options

## Greeks unit contract

The SDK raw values are retained for audit. User-facing normalized values follow the documented API units:

- Delta: option-price change per one underlying-price unit.
- Gamma: Delta change per one underlying-price unit.
- Theta: raw API value divided by 100, expressed as option price per share per day.
- Vega: raw API value divided by 100, expressed as option price per share per one volatility point.
- Rho: raw API value divided by 100, expressed as option price per share per one interest-rate point.

Large 0DTE shocks must use full repricing. Local Greeks are displayed only as limited attribution and never as a fill price or real-world probability.

## Required data upgrades

### Required before strict intraday simulation

1. OPRA realtime option quote entitlement for the Longbridge OpenAPI account.
2. A source that provides bid, ask, bid size, ask size, and a native exchange or provider event timestamp.
3. Complete earnings, ex-dividend, company announcement, and macro-event publication timestamps.
4. Explicit option fee assumptions and a dated fee-policy version.

### Required before historical performance claims

1. Historical option bid/ask or quote data at the decision and exit timestamps.
2. Contract master history including adjusted deliverables, splits, special dividends, expiries, and delistings.
3. Dated open interest, trade volume, IV surface, rates, and dividend inputs.
4. Sufficient independent completed outcomes for each direction and horizon group.

Underlying-stock replay or theoretical option pricing cannot replace historical option execution evidence.

## Budget and approval status

- Current incremental spend: `0`.
- No market-data package was purchased or enabled by Codex.
- Longbridge OPRA price and availability can vary by account and region; obtain an account-specific quote before approval.
- Historical option quote data and event calendars require separate vendor coverage and licensing review.
- Purchase decision remains with the user. The system stays observation-only until entitlements are verified by a new audit run.

## Safety boundary

The radar supports long Call and long Put research, one-contract simulation, Web/SSE/Web Push/Telegram alerts, and manual review. It has no option order, account, position, exercise, assignment, or broker route. Existing legacy option Paper records are excluded from radar performance.
