# KQUANT Strategy Specification

Status: Day 3 scope freeze

## Active Strategy

Only `swing_long_v1` is active in the 84-day validation program. Its immutable
initial version is `swing_long_v1.0.0`. A changed configuration requires a new
strategy version and configuration hash; it must never silently overwrite past
signals, labels, backtests, or AI action events.

## Intent

- Direction: long-only.
- Holding period: approximately one week to two months.
- Primary decision bar: completed daily candle.
- Confirmation bar: completed 1-hour candle.
- Market: liquid US-listed stocks and ETFs in the point-in-time universe.

## Frozen v1.0.0 Parameters

| Item | Value |
|---|---:|
| BUY setup threshold | 82 |
| Strict BUY gate score | 88 |
| WATCH threshold | 65 |
| Daily trend | `close > EMA20 > EMA50 > EMA200` |
| 1-hour confirmation | `close > EMA20 > EMA50` and momentum >= 0.6% |
| Volume confirmation | volume ratio >= 1.2 |
| Maximum ATR | 5.0% |
| Maximum daily extension | 5.5% |
| Historical focus win rate | >= 55% |
| Historical focus average return | >= 0.4% |
| Initial stop reference | 3.5% |
| Target reference | 2.0% |

These numbers are a frozen baseline, not a claim of expected performance. They
cannot be tuned from current results before the point-in-time validation and
walk-forward work in Weeks 4 and 5.

## Input Contract

Every decision must use only data known at the signal timestamp:

- Daily and 1-hour OHLCV data with source lineage, bar state, freshness, and
  exchange-session metadata.
- Deterministic EMA, momentum, volume, ATR, extension, relative-strength, and
  market-regime features.
- Point-in-time universe membership.
- Historical evidence that is explicitly tagged with sample count and quality.
- Hard-veto state produced by deterministic code.

AI receives the structured feature packet for ranking and plan wording. It may
not invent a feature, remove a veto, or convert reference-only data into a BUY.

## Entry and Exit Semantics

- A signal is generated only after the signal bar is complete.
- Historical validation enters at the next eligible bar open.
- The entry plan defines an entry zone, a stop, a target, a no-chase rule, and
  an invalidation condition.
- When stop and target are both touched in the same historical bar, the result
  is conservatively recorded as stop first.
- Transaction costs, spread/slippage, and gap risk are included in validation.

## Hard Vetoes

Any veto below blocks a BUY action regardless of rule score or AI output:

- Longbridge primary data unavailable, stale, partial, or reference-only.
- Missing or forming required decision bars.
- Missing entry, stop, target, or invalidation.
- Market risk block, unacceptable ATR/liquidity/event risk, or data-quality
  failure.
- Evidence quality below the active real-money gate.

## Frozen Modules

All other profiles, high-beta probe logic, options, MSTR radar expansion,
crypto, and additional agents remain in the repository but do not receive
strategy changes during this program phase.
