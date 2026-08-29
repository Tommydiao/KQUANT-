# Market Data Quality Policy

## Machine-readable decision

Every normalized candle payload now includes `data_quality`. The decision has
three states:

- `clean`: usable as the primary Longbridge market-data input, subject to the
  separate strategy rules.
- `caution`: visible for research but includes an explicit limitation.
- `blocked`: cannot support a buy/probe conclusion or be described as clean
  validation evidence.

The payload includes source, provider status, adjustment mode, dataset version,
coverage, integrity counts, freshness, hard-veto reasons, and caution reasons.

## Hard vetoes

The gate blocks empty data, malformed OHLCV, malformed/duplicate/future candle
times, unavailable or stale providers, Yahoo reference data, fixture data, and
stale intraday data. The realtime decision additionally requires regular
session, `live_quote` trust, a fresh Longbridge quote, and available depth.

Forming candles remain displayable, but are labelled as excluded from closed-bar
confirmation. Suspected corporate actions keep their raw price lineage and add
a caution until manually resolved.

## Scope boundary

This gate is deterministic data-quality logic. It does not infer a trade,
silently repair data, or submit an order. Historical validation still needs
authorised membership and corporate-action feeds before it can claim a fully
point-in-time dataset.
