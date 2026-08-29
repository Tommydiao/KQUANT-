# Point-in-Time Universe Policy

## What is stored

Whenever the stock-universe API is used with a local database, KQUANT stores the
exact membership supplied to that run in `stock_universe_snapshots` and
`stock_universe_memberships`. Each snapshot carries the New York market date, a
content hash, source label, and the complete symbol metadata used for selection.

The content hash is part of the identity. If the current static universe changes,
the changed composition becomes a distinct snapshot rather than rewriting an
older one.

## Evidence boundary

These snapshots start on the date KQUANT begins recording them. They do not
reconstruct historical index membership, delistings, IPO availability, or past
liquidity eligibility. A historical replay that draws candidates from the
runtime universe must therefore report:

- `survivorship_limited: true`
- `historical_membership_complete: false`
- the available snapshot-date coverage and the exact limitation text

It cannot be described as a point-in-time universe backtest or used as robust
evidence for a strategy decision.

## Future completion criteria

Point-in-time validation may only become eligible after an authorised historical
universe source provides dated membership and eligibility data. Import jobs must
store source/version, effective dates, delisting and IPO handling, and a
reproducible membership query for every signal date. Until then, current runtime
snapshots are audit records, not substitute history.
