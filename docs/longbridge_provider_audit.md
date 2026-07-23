# Longbridge Provider Audit

Audit date: 2026-07-23 (Asia/Shanghai)  
Audit mode: local, read-only, credential-safe

## Result

The Longbridge Python SDK is installed, but no Longbridge credentials were
present in the checked `.env` file or current process. The provider is therefore
correctly unavailable for live quote/depth verification. KQUANT returned
`caution`; it did not silently upgrade Yahoo data into a real-time conclusion.

No credential value was read, printed, logged, or stored by this audit.

## Observed environment

| Check | Result |
| --- | --- |
| Longbridge SDK | Installed: `4.4.1` |
| `KQUANT_MARKET_DATA_PROVIDER` | Not configured |
| `LONGBRIDGE_APP_KEY` | Not configured |
| `LONGBRIDGE_APP_SECRET` | Not configured |
| `LONGBRIDGE_ACCESS_TOKEN` | Not configured |
| Quote entitlement | Not verifiable; reported unavailable/standby |
| Depth entitlement | Not verifiable; reported unavailable |
| Database audit write | Pass |
| Account context | Disabled |
| Trade context | Disabled |
| Order submission | Disabled by runtime boundary |

At the audit time, the XNYS fallback calendar identified 2026-07-23 as a
trading day with a 13:30-20:00 UTC regular session. The observed session was
`pre_market`; it cannot support a fresh buy-class action even with a valid quote.

## Implemented provider design

- A single persistent read-only `QuoteContext` is held by
  `kquant.longbridge_provider.LongbridgeReadOnlyRuntime`.
- The runtime exposes quote, depth/BBO, historical/realtime candlesticks, and
  US trading-day operations. It does not create a trade or account context.
- Symbol subscription lifecycle includes active-symbol replacement, unsubscribe,
  subscription count tracking, timeout handling, and context reset after a
  provider error.
- Quote freshness is checked at 15 seconds during the regular session.
- Intraday Longbridge bars are stale during regular hours when the latest
  expected close exceeds `max(2 * interval_seconds, 180 seconds)`.
- Calendar calls prefer Longbridge when configured, cache the result in SQLite,
  and fall back deterministically to `exchange_calendars:XNYS`.
- Yahoo is display/reference fallback only. `yahoo_reference_only`, stale
  Longbridge cache, missing depth, a non-regular session, or a forming bar
  blocks new buy-class action.

## Verification performed

- Provider self-check used an isolated SQLite audit database and returned no
  credential values.
- `tests/test_longbridge_runtime.py`, realtime strategy tests, market-clock
  tests, and dashboard tests passed within the 19-test regression group.
- The full Python suite passed: `67 passed` with one upstream test-client
  deprecation warning.

## Credentialed smoke procedure

This remains manual and opt-in. Before enabling it, rotate any token that may
have appeared in a screenshot or shared terminal.

1. Set `KQUANT_MARKET_DATA_PROVIDER=longbridge` and the three Longbridge values
   in the local `.env` file only.
2. Restart the local terminal with `start_kquant_stock_terminal.ps1`.
3. Call `GET /api/stocks/market-data/self-check?symbol=SPY` during a US regular
   session. Confirm only configured/missing status is shown for credentials.
4. Confirm quote status is `available`, depth status is `available`, quote age
   is at most 15 seconds, calendar source is recorded, and the route audit
   still reports no account/trade/order context.
5. Call `GET /api/stocks/realtime-snapshot?symbol=SPY`; confirm a fresh
   `live_quote` trust state and correctly marked forming/closed bars.
6. If any check fails, keep KQUANT in paper-observed/reference mode. Do not
   treat Yahoo or cached data as support for a fresh buy decision.

## Next action

Day 9 may improve canonical candle persistence without credentials. A
credentialed provider audit must be repeated after the user deliberately adds
new, rotated Longbridge credentials.
