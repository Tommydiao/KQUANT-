# Corporate Action Policy

## Purpose

Corporate actions can make an otherwise valid price series discontinuous. KQUANT
must expose that uncertainty instead of silently rewriting prices, signals, or
backtest outcomes.

## Current implementation

`kquant.market_store.persist_canonical_candles` compares each newly accepted
closed candle with the preceding canonical close for the same symbol, interval,
adjustment mode, and dataset version. A close-to-close move that is within four
percent of a 2:1, 3:1, 4:1, 5:1, or 10:1 split (or the corresponding reverse
split) is stored in `corporate_action_events` as one of:

- `suspected_split`
- `suspected_reverse_split`

The event is deliberately recorded with `status = caution`, its source, the
observed prices, the estimated ratio, and the detection time. It is evidence for
review, not a declaration that a corporate action occurred.

## Non-negotiable safeguards

- Detection never alters an observed candle or replaces its declared
  `adjustment_mode`.
- Detection never adjusts a position, feature packet, strategy signal, journal,
  or historical backtest result.
- A fallback provider cannot overwrite a higher-priority canonical observation.
- A dataset used for validation must keep one explicit adjustment mode and
  dataset version. Mixed or unresolved action periods are a data-quality
  limitation, not proof of a strategy result.

## Review and future work

An operator must verify a suspected event against the authorised provider or an
issuer record before accepting an adjusted dataset. The next data-quality phase
will add a review state and prevent validation from presenting affected periods
as robust evidence until the adjustment lineage is resolved. KQUANT currently
does not ingest an automatic corporate-action feed and must therefore label this
limitation in all historical claims.
