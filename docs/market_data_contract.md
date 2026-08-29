# Market Data Contract

Status: contract frozen for the 84-day plan; implementation alignment follows

## Purpose

This contract separates data that may be displayed from data that may support a
new manual long review. It protects KQUANT from silently treating delayed,
fallback, incomplete, or mixed-source data as live trading evidence.

## Time and exchange contract

- Backend timestamps use UTC ISO-8601 with an explicit offset.
- The exchange timezone is `America/New_York`; the default display timezone is
  `Asia/Shanghai`.
- Trading days, regular open/close, early closes, weekends, holidays, and DST
  are resolved from Longbridge when available and cached in SQLite. The
  `exchange_calendars:XNYS` calendar is the deterministic fallback.
- Session labels are `pre_market`, `regular`, `after_hours`, or `closed`.
- Only the US `regular` session may support a fresh buy-class decision.

## Source precedence

| Source/state | Display | Historical/reference research | New buy-class review |
| --- | --- | --- | --- |
| Longbridge quote + depth + closed Longbridge bars | Yes | Yes | Yes, if all freshness and session gates pass |
| Longbridge closed-bar cache | Yes, marked stale | Yes, marked stale | No |
| Yahoo public fallback | Yes, marked `yahoo_reference_only` | Reference only | No |
| Fixture data | Tests only | Tests only | No |
| Missing, malformed, or future-dated data | No conclusion | No | No |

KQUANT must never merge source families into a single unlabelled candle series.
When Longbridge is configured as the primary provider, both daily and 1H bars
for a buy-class candidate must be `longbridge_candles` and `available`.

## Quote and BBO contract

- Quote fields are `last`, `bid`, `ask`, `bid_size`, `ask_size`, `spread`,
  `spread_pct`, `quote_time`, and `freshness_seconds`.
- BBO comes from Longbridge depth when the entitlement is available. Missing BBO
  is a data-quality failure for a fresh buy-class review during regular hours.
- During a regular session, a quote is fresh only at age `<= 15 seconds`.
- A quote may update a visible forming 1-minute bar; it cannot close a bar or
  confirm a strategy signal.

## Candle contract

Each retrieved candle must carry, or be derivable with no ambiguity from, these
fields:

```text
symbol, interval, open_time_utc, open, high, low, close, volume,
source, provider_status, fetched_at_utc, freshness_seconds,
bar_state, adjustment_mode, dataset_version
```

- `open_time_utc` is the opening time, not a rendered display label.
- `bar_state` is `forming_candle` or `closed_candle`.
- Forming candles can update the chart only. Features, classification, AI
  packet state, validation signals, and backtests use closed candles only.
- 5-minute candles are aggregates of their 1-minute components. A 5-minute bar
  is closed only after all five component 1-minute bars are closed; partial
  component counts remain forming.
- Duplicate fetches must upsert the same logical observation. The target
  canonical identity is `(symbol, interval, open_time_utc, adjustment_mode,
  dataset_version)`. Provider/source observations remain traceable metadata,
  not a reason to create unlabelled duplicate market bars.
- Invalid OHLC (`low > high`, non-positive prices, non-finite values) or a
  future timestamp is rejected and emits a provider event.

## Freshness and trust states

`/api/stocks/realtime-snapshot` exposes one of these trust states:

- `live_quote`: fresh Longbridge quote and available Longbridge intraday bars.
- `stale_longbridge_cache`: a cached Longbridge observation is available but
  cannot support new buy-class action.
- `yahoo_reference_only`: public fallback/reference data only.
- `unavailable`: no usable timely source.

For intraday Longbridge bars, stale during a regular session means the most
recent expected bar close is older than `max(2 * interval_seconds, 180 seconds)`.
Outside regular hours, values are labelled `market_closed`, not live triggers.

## Adjustment and corporate-action policy

Until Day 11 implements company-action support, the provider adjustment mode
must be explicitly persisted. A dataset may not mix adjusted and unadjusted
prices. Any known split, dividend, symbol change, or unexplained discontinuity
creates a `corporate_action_caution` state that blocks backtest comparisons and
fresh strategy conclusions until reviewed.

## Missing and degraded data

The following produce `DATA_CAUTION` and hard-veto new buy-class action:

- unavailable, stale, rate-limited, malformed, or future-dated required data;
- no regular-session Longbridge quote/depth where a current decision is needed;
- missing daily/1H history or a forming confirmation bar;
- Longbridge failure followed by Yahoo reference fallback; and
- database write failure for the requested data/audit event.

The UI must state the source and reason. It must not invent values, substitute
fixture data, or keep an old BUY conclusion without marking it stale.

## Storage and audit requirements

- SQLite stores raw candle payload fields, source, provider status, freshness,
  fetched time, and data-quality events. The canonical `market_candles` table
  is unique by `(symbol, interval, open_time_utc, adjustment_mode,
  dataset_version)`; `market_candle_observations` retains every source's
  observation without allowing a lower-priority fallback to overwrite a
  Longbridge primary record.
- Each signal, journal entry, validation run, and report references its market
  dataset/version and strategy version.
- Credential values never enter SQLite, API responses, logs, reports, or the
  frontend bundle. Health checks report only configured/missing state.

## Verification requirements

Automated tests must cover DST, holiday, early close, session boundaries,
forming/closed transitions, 1m-to-5m aggregation, quote freshness, source
fallback, duplicate upsert, future timestamps, provider timeout, and database
write failure. A real Longbridge smoke is manual and opt-in; regular CI uses
mocks and no credentials.
