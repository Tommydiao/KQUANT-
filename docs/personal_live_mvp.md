# KQUANT Personal Live MVP

Status: Day 2 scope freeze

## Purpose

KQUANT is a private, read-only decision-support system for one human trader.
It may produce research signals and a trade plan, but it never accesses an
account, reads positions, submits an order, or promises a return.

## In Scope

- Market: liquid US-listed stocks and ETFs only.
- Direction: long-only.
- Active validation strategy: `swing_long_v1`.
- Intended holding period: approximately one week to two months.
- Decision timeframes: daily trend with a completed 1-hour confirmation bar.
- Primary data: Longbridge read-only US quote and candle data.
- Reference-only data: Yahoo public chart data. It may be displayed with an
  explicit label but cannot support a real-money BUY decision.
- Execution: manual in the trader's own broker application.
- Record keeping: a pre-trade and post-trade journal entry for every manual
  trade or explicit skip.

## Standard User Flow

1. Start KQUANT and run the local self-check.
2. Confirm Longbridge data is available, fresh, and in the regular session.
3. Generate or open the current daily shortlist for `swing_long_v1`.
4. Open one symbol and review the completed daily and 1-hour bars.
5. Review the deterministic entry, stop, target, invalidation, risk/reward,
   and data-quality state.
6. Treat AI output as a structured research plan. The hard-veto result wins
   over an AI recommendation.
7. Save the journal plan before making any manual order outside KQUANT.
8. Record the outcome and any plan deviation after the position is closed.

## No Trade Conditions

The correct decision is `NO TRADE` when any condition below is true:

- Longbridge is unavailable, stale, lacks US quote entitlement, or returns a
  partial/invalid response.
- The decision uses Yahoo/reference-only data rather than fresh Longbridge
  data.
- A required daily or 1-hour candle is forming, missing, stale, or outside the
  documented trading-session contract.
- The active strategy version, data snapshot, entry, stop, target, or
  invalidation is missing.
- A hard veto is active: provider failure, severe staleness, market risk
  block, unacceptable volatility/liquidity, or incomplete plan.
- Historical evidence is marked insufficient or limited for a real-money
  decision.
- The journal entry has not been saved.

## Explicitly Excluded

- Options, leveraged ETFs, short selling, crypto, MSTR-specific expansion,
  account/position reads, broker order APIs, paper execution, and automatic
  execution.
- The frozen profiles `tactical_1w_v1`, `swing_1_2m_v1`, `position_6m_v1`,
  `cycle_1_3y_v1`, and `high_beta_growth_v1` are visible legacy research
  modules only. They are not part of formal validation or the Personal Live
  MVP decision path.

## MVP Acceptance Criteria

The MVP is ready to begin forward observation, not real-money trading, only
when all of the following are true:

- Every reviewed symbol has a fresh Longbridge primary-data record with
  provider lineage and bar state.
- Every signal references an immutable strategy version and configuration hash.
- The validation suite, frontend build, runtime self-check, and secret scan
  pass from one command.
- The system can produce and retain a complete journal record without an order
  integration.
- The trader can identify a clear `NO TRADE` reason without reading internal
  implementation diagnostics.
