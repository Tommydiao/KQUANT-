# KQUANT Market Data Contract

Status: Day 4 data contract

## Provider Roles

| Provider | Role | Real-money eligibility |
|---|---|---|
| Longbridge read-only quote/candles | Primary US market-data source | Required for BUY-class research actions |
| Longbridge stale cache | Recovery evidence only | Never sufficient for BUY |
| Yahoo public chart | Reference-only historical fallback | Never sufficient for BUY |
| Fixture data | Internal tests only | Never user-visible, never tradable |

KQUANT uses no account, position, or trading context from Longbridge.

## Time Contract

- Storage time is UTC ISO-8601 with an explicit offset.
- `open_time` is the start of the candle interval, not the publication time.
- The exchange calendar is `America/New_York`; display defaults to
  `Asia/Shanghai` while preserving a New York-time toggle in the UI.
- The market clock handles US daylight saving time, weekends, published US
  holidays, and documented early closes.
- A naive provider timestamp is interpreted as UTC only when the provider
  contract documents it as UTC. It is never silently treated as New York time.

## Session and Candle State

| State | Meaning | Eligible for signal generation |
|---|---|---|
| `live_quote` | Current quote with provider timestamp | Quote display only |
| `forming_candle` | Current unclosed interval updated by quote | No |
| `closed_candle` | Completed exchange interval | Yes |
| `stale_longbridge_cache` | Previously real Longbridge data | No |
| `yahoo_reference_only` | Public reference data | No |
| `provider_failed` | Required response absent or invalid | No |

The current quote may update a forming 1-minute bar. A five-minute bar is
formed by aggregating complete one-minute bars and must remain forming until
its interval closes.

## Freshness Rules

- Quote freshness is evaluated against provider quote time, not browser time.
- Regular-session quote freshness target is 15 seconds.
- Maximum intraday bar lag for a live trigger is 180 seconds.
- Provider status, source type, quote time, candle time, session, bar state,
  and stale age are returned with every relevant API response.
- Freshness failure applies the hard veto before any AI BUY-class action.

## Price and Corporate Actions

- Raw and adjusted series must never be mixed within one validation run.
- The current implementation stores provider-returned OHLCV and source lineage;
  explicit split/dividend adjustment policy and corporate-action processing are
  Week 2 tasks, not assumed complete today.
- A validation run must declare its adjustment convention and reject mixed
  conventions.

## Storage and Idempotency

- Candle identity is `(symbol, interval, open_time, source)`.
- Writes are idempotent for an identical source/time candle.
- Source lineage and provider status are retained; a stale cache is never
  relabeled as live.
- Signals and outcomes bind the data source plus immutable strategy version and
  configuration hash.
