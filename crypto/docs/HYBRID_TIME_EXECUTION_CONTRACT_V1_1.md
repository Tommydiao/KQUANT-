# Hybrid Time and Execution Contract V1.1

Status: M1 contract, runtime integration DISABLED. Owner: integration task.
Authority: user Hybrid V1.1 sections 3, 4, 5, 8, 12. Original strategy remains
`crypto_spot_dual_regime_v1.0.0`. New code must not reinterpret old run fields.

## Time

All new times are finite nonnegative UTC epoch seconds; subsecond values are
allowed. Existing integer `Bar.start` is unchanged. The economic signal names
the 5m close, not model completion. Each feature must have available_at <=
snapshot_frozen_at. Snapshot <= evaluation start <= finish <= commit <= earliest
fill < expiry. Model availability must precede evaluation start. decision_time,
if exposed by a future Hybrid API, aliases commit only.

`hybrid_contracts.DecisionTimeline` is an offline executable contract. Its fill
predicate requires earliest_fill_at < market event time <= receipt <= expiry.
This selects the stricter 'after' reading of section 5.2; same-time events are
not eligible without a separately versioned total-order contract. It does not
certify source, BBO, size, risk, price geometry or portfolio version.

At 10:00:03 model completion and 10:00:04 commit, 10:00:00 open is unavailable
for a new fill even if received later. OHLC-only experiments wait for the next
eligible actual bar open, never interpolate a 10:00:04 price. Expiry can mean no
eligible bar exists. No silent expiry extension is permitted.

## Execution Types

| Type | Contract | Current status |
| --- | --- | --- |
| LEGACY_BAR_PROXY | Original next-open and original protection ordering | Existing baseline, unchanged |
| DELAYED_BAR_PROXY | Later-than-commit open; original protection rules afterward | Contract only |
| QUOTE_AWARE | Actual later bid/ask, measured receipt, source/size/freshness validation | Hybrid contract only |

No runtime latency, queue or model timeout budget is frozen yet. The existing
30-second candidate delay setting is not proof that mathematical inference can
fit that budget. Measure bounded workers offline before enabling any new entry.

## Two Lanes and One Writer

Protection accepts trusted events for an existing symbol independently of the
three-symbol new-entry batch. It never awaits an LLM/MC/Bayesian future. Invalid
or missing SOL new-entry data cannot delay BTC protection. Missing executable
BTC quote produces EXIT_PENDING_NO_VALID_QUOTE, not a fabricated exit.

The sole ledger writer serializes: (1) valid protection/hard-risk transitions,
(2) cancellations and expiration, (3) new-entry commits in BTC/ETH/SOL order.
Workers produce immutable evaluations without ledger references. A protection
transition increments portfolio_version and invalidates older entry results.
No runtime lane implementation is claimed by the pure timeline tests.

Before a new batch is consumed, validate all three identities, aligned closed
5m bars, full 12-child hourly evidence at hourly closes, ordering and duplicates.
Reject an incomplete batch atomically for new entries only.

Preserve original opening-gap precedence, pending exits before entry, protection
on the entry bar, stop-first ambiguous interior, 72/36-bar limits, quote bid exit,
cooldown, old UTC day's final risk test and next valid opening baseline. A model
timeout must not clear exits, extend targets or reset the daily risk allowance.

## Transaction and Stop Contracts

Final commit compares portfolio_version and the full model/feature/policy/cost/
execution/risk snapshot identity. On mismatch: ABSTAIN_PORTFOLIO_CHANGED, no
reservation. Re-evaluation budget remains unresolved; default no automatic retry.
Intent, reservations, consumed identity, audit and checkpoint commit together.
At fill, revalidate expiry, original price rules, cash and hard risk; no model
refit using the later price. DB failure cannot advance authoritative memory.

Planned stop-new-entries cancels entry intents while protection continues;
drain waits for protected exposure to exit; force-stop requires explicit extra
confirmation and records unprotected interruption. These are NOT CLI commands
implemented in this milestone. Do not invoke the existing candidate stop to
simulate their implementation.
