# KQUANT Personal Live MVP

Status: scope frozen for the 84-day plan

## Product definition

KQUANT is a decision-support terminal for one owner who manually trades
long-only US stocks and ETFs. Its job is to make a candidate review repeatable:
show reliable market data, apply a fixed rule set, expose uncertainty, define
entry/stop/target, and keep a journal.

`Live` in this document means the owner may use the research to make a manual
trade in a separate brokerage application. It does **not** mean KQUANT connects
to a brokerage account, reads holdings, or submits an order.

## Target user

- One experienced owner, operating locally on a trusted Windows computer.
- US listed stocks and ETFs only; long positions only.
- Primary holding window: approximately one week, with a fixed daily-trend and
  1-hour confirmation workflow.
- The user remains responsible for position size, order placement, and every
  execution decision.

## Daily workflow

The main workflow has six steps. A blocked step ends the workflow; it never
falls through to a trade suggestion.

1. **Start and self-check**: open KQUANT, confirm database write access,
   Longbridge credentials/SDK/quote entitlement, market calendar, and the
   read-only route scan. Secrets are reported only as configured or missing.
2. **Establish market state**: read regular-session status, SPY/QQQ/IWM/VIX
   regime, provider health, and the market-data trust label. `DATA_CAUTION` or
   `RISK_OFF` blocks new long review.
3. **Scan the frozen universe**: run the canonical `swing_long_v1.0.1` scan on
   the point-in-time eligible universe. Use Longbridge closed daily and 1-hour
   bars for any candidate that could advance.
4. **Review one candidate**: check the rule level, score components, price and
   BBO freshness, daily/1-hour structure, entry/stop/target, R:R, historical
   evidence, hard veto, and AI explanation. AI is context, never permission.
5. **Decide and journal**: if every gate is clear, save the entry, stop,
   target, invalidation, and decision note in KQUANT. Any execution then occurs
   manually outside KQUANT. Otherwise record `watch`, `skipped`, or
   `paper-observed`.
6. **Close the loop**: update the journal with outcome and reason, inspect data
   incidents, and review whether the action behaved as the recorded plan said.

## Required MVP capabilities

- A point-in-time US stock/ETF universe with an auditable membership history.
- Longbridge quote, BBO, daily bars, and 1-hour bars with explicit freshness,
  session, source, and candle-completion state.
- Clearly marked Yahoo reference fallback that hard-vetoes new buy-class action.
- One versioned deterministic strategy: `swing_long_v1.0.1`.
- Market-regime, data-quality, liquidity, risk/reward, and historical-evidence
  gates that cannot be bypassed by AI.
- Entry, stop, target, invalidation, position-risk guidance, and a manual
  journal. These are research plans, not executable orders.
- Historical policy replay and prospective AI-action evidence reported as two
  separate datasets.
- A repeatable local verification command and CI with no real credentials.

## Explicitly paused

- Automated, broker, account, position, portfolio, or order APIs.
- Options, short sales, leverage, margin, crypto assets, and crypto exchanges.
- MSTR/BTC or other underlying-crypto special research paths.
- Additional strategy profiles, new indicator families, social/community
  features, mobile apps, and unrelated visual redesign.
- AI agents that create data, alter scores, override vetoes, or execute trades.

## MVP release conditions

The research terminal may be used for paper-observed work only when all of the
following are true:

- the current strategy version, data contract, and source policy are published;
- the route boundary scan, test suite, and production frontend build pass in a
  freshly created local environment;
- Longbridge health, calendar, quote, and depth are verified without exposing
  credentials;
- every buy-class candidate uses clean Longbridge data, closed confirmation
  bars, a regular US session, and a hard-veto-clear market state;
- the journal can record a complete plan and outcome; and
- historical and prospective evidence are visibly labelled as different
  evidence chains.

## Not a real-money release condition

No manual real-money use is approved merely because the UI shows a `BUY`,
`WATCH`, or AI action. It remains blocked until the later Go/No-Go gates in the
84-day plan are met, including reproducible validation, at least 100 completed
historical samples, positive out-of-sample expectancy after costs, acceptable
drawdown, and at least 15 full forward/paper trading days without a safety or
data-integrity failure.

## Current alignment gaps

- The implementation still exposes legacy profile names alongside
  `swing_long_v1`; the user-facing and validation default must converge on the
  canonical version after the version registry exists.
- Some legacy copy in the signal module mentions options even though no options
  route exists. That copy must be removed during scope-alignment cleanup.
- The local Python environment must be restored before any capability is
  accepted as currently verified.
