# Monday Live Manual Pilot Runbook

This runbook is for the first small-size manual real-money pilot. KQUANT remains
read-only: no broker connection, no account access, no paper/live/testnet order
path, and no automatic execution.

## Goal

Use KQUANT to select, verify, and journal a very small number of US stock
trades. The system provides AI-led research signals and a manual trade plan,
while hard guardrails block bad data, stale providers, poor risk/reward, and
unsafe setups.

## Hard Limits

- Stocks only.
- No options.
- No leveraged ETFs.
- No averaging down.
- No chasing outside the AI entry zone.
- Maximum risk per trade: `0.25%` of account equity.
- Maximum first-day trades: `1-2`.
- Maximum first-day total risk: `0.5%`.
- Journal before entry is mandatory.
- `NO TRADE` means no real-money trade.

## Pre-Market: 30-60 Minutes Before Open

1. Run the one-click preflight:

   ```powershell
   .\KQUANT_MONDAY_PREFLIGHT.cmd
   ```

   This starts or reuses the local backend, refreshes the AI Daily report,
   runs the readiness audit, opens the dashboard, and writes
   `outputs/monday-pilot-readiness.md/json`.

2. Confirm the Monday readiness panel:
   - Live API is online.
   - AI Agent is available.
   - Real Data Guard says no fixture.
   - AI Daily report is fresh.
   - Broker/account/order wiring is disabled.
3. If readiness is `NO_TRADE`, switch to observation-only for the day.
4. If readiness is `CAUTION`, only observe unless the specific caution is
   understood and not related to the candidate's required data.

## Open: First 15-30 Minutes

1. Do not chase the opening impulse.
2. Review `AI Today`.
3. Focus only on:
   - Top AI buy candidates.
   - Watch-for-pullback names.
   - High-Beta Growth candidates only if explicitly marked for that profile.
4. Ignore any idea without live daily and confirmation candles.

## Candidate Review

For each candidate, walk through:

1. AI Trading Command:
   - action;
   - confidence;
   - entry zone;
   - stop zone;
   - target zone;
   - risk/reward;
   - position size hint;
   - invalidated-if condition.
2. Manual Trade Ticket:
   - cleared for review must be true;
   - R/R must be at least `2.0`;
   - stop must be explicit;
   - no hard veto.
3. K-Line:
   - daily trend agrees with the setup;
   - confirmation timeframe is not breaking down;
   - avoid buying into a failed breakout or extended exhaustion.
4. Deep Research:
   - ask what would invalidate the setup;
   - ask what entry is better if the current price is stretched.
5. Journal:
   - record reviewed/skipped/entered manually;
   - record planned entry, stop, target, and risk amount.

## Entry

Only consider manual entry when all are true:

- AI action is `AI_BUY_CANDIDATE`;
- live daily and confirmation candles are available;
- hard veto is false;
- provider is not failed or severely stale;
- risk/reward is at least `2.0`;
- stop zone is clear;
- position size hint is clear;
- journal is written before entry.

## Intraday Management

- If price hits invalidation, review or exit manually.
- If price reaches the first target zone, consider partial profit or trailing
  the stop.
- If total daily risk reaches `0.5%`, stop trading.
- Do not add to a losing position unless a future runbook explicitly allows it.

## After Close

1. Update every journal entry:
   - followed plan or not;
   - entry and exit notes;
   - result;
   - whether AI/K-line evidence helped.
2. Record data issues:
   - provider failed;
   - stale cache;
   - AI unavailable;
   - chart mismatch.
3. Do not change core rules intraday based on one trade. Review changes after
   several sessions of journal evidence.

## Emergency Stop

Stop real-money trading immediately if:

- KQUANT readiness switches to `NO_TRADE`;
- live candles disappear for the active symbol;
- AI produces an action that conflicts with hard veto;
- broker/order wiring appears anywhere in the UI;
- you cannot write a journal note before entry.
