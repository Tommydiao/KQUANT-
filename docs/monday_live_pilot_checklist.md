# Monday Manual-Money Pilot Checklist

Use this checklist for the first small-size real-money manual pilot. KQUANT is
read-only research software: it does not connect to a broker, read an account,
or submit orders. If any critical item fails, stop and switch to observation.

## 1. Preflight

- [ ] Run `KQUANT_MONDAY_PREFLIGHT.cmd`.
- [ ] Confirm the preflight result is `READY`.
- [ ] Save or keep open `outputs/monday-pilot-readiness.md`.
- [ ] Confirm `Live API` is online.
- [ ] Confirm `AI` is available.
- [ ] Confirm `Real Data Guard` says no fixture data.
- [ ] Confirm broker/account/order wiring is disabled.
- [ ] Confirm AI Daily report is fresh for the current trading day.

Developer-only regression:

- [ ] Run `KQUANT_VERIFY.cmd` before pushing or freezing a new code build.

Decision:

- [ ] If status is `NO_TRADE`, do not trade real money.
- [ ] If status is `CAUTION`, trade only if the caution is unrelated to the
  exact candidate and the reason is written in the journal.
- [ ] If status is `READY`, continue to candidate review.

## 2. First 15-30 Minutes

- [ ] Do not chase the opening impulse.
- [ ] Review `AI Today`.
- [ ] Review only Top AI candidates and Watch-for-pullback names.
- [ ] Ignore any stock without live daily and confirmation candles.
- [ ] Ignore any candidate outside its planned entry zone.

## 3. Candidate Gate

For each candidate:

- [ ] AI action is `AI_BUY_CANDIDATE`.
- [ ] Hard veto is false.
- [ ] Daily K-line is available and agrees with the setup.
- [ ] Confirmation K-line is available and not breaking down.
- [ ] Provider status is not failed or severely stale.
- [ ] R/R is at least `2.0`.
- [ ] Entry zone is specific.
- [ ] Stop zone is specific.
- [ ] Target zone is specific.
- [ ] Position size hint is specific.
- [ ] Invalidation condition is specific.
- [ ] Deep Research was checked for risks and better entry.

If any item fails, mark the idea as `skipped` or `watch` in the journal.

## 4. Risk Limits

- [ ] Stocks only.
- [ ] No options.
- [ ] No leveraged ETFs.
- [ ] No averaging down.
- [ ] No chasing.
- [ ] Max risk per trade is `0.25%` of account equity.
- [ ] First-day max trades: `1-2`.
- [ ] First-day total risk cap: `0.5%`.
- [ ] If the daily risk cap is hit, stop trading.

## 5. Journal Before Entry

Before any manual entry:

- [ ] Save a stock journal entry.
- [ ] Status is `entered-manually` only if an entry is actually placed.
- [ ] Planned entry is recorded.
- [ ] Planned stop is recorded.
- [ ] Planned target is recorded.
- [ ] Notes explain why the setup passes the gate.
- [ ] Notes confirm whether the execution follows the AI plan.

No journal means no trade.

## 6. Intraday Management

- [ ] If invalidation triggers, review or exit manually.
- [ ] If first target is reached, consider partial profit or trailing stop.
- [ ] Do not add to losing positions.
- [ ] Do not move the stop farther away to avoid taking a loss.
- [ ] If KQUANT switches to `NO_TRADE`, stop taking new trades.

## 7. After Close

For every reviewed candidate:

- [ ] Update the journal.
- [ ] Mark `exited-manually` if an exit happened.
- [ ] Record followed-plan vs deviated-from-plan.
- [ ] Record whether AI, K-lines, and Deep Research helped.
- [ ] Record provider, AI, or chart issues.
- [ ] Save the readiness report with the journal notes.
- [ ] Do not change core rules based on one trade.

## Emergency Stop

Stop real-money trading immediately if:

- [ ] Live candles disappear for the active symbol.
- [ ] AI produces a buy candidate while hard veto is active.
- [ ] Broker, account, paper order, live order, or testnet order paths appear.
- [ ] You cannot write a journal note before entry.
- [ ] You feel pressure to chase, average down, or exceed the risk cap.
