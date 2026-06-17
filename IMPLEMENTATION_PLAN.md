# kquant US Options Implementation Plan

## Current Direction

kquant is now an Options-first research terminal. BTC/ETH 15m research remains
in the codebase only as a legacy sandbox and should not receive new product
work unless it is needed for archival or removal.

The active rollout is a 3-trading-day Live Pilot for manual ATM Options review.
The default dashboard entry is cache-first live data; full public-data scans are
manual to reduce provider rate-limit pressure. The LLM signal core is locked:
no external model may set alert scores, alert levels, scans, or any broker/order
action during this phase.

The current product target is a read-only US options workflow:

- scan liquid US equities for momentum and relative-volume setups;
- show broker-style option chains with expiration, strike, bid/ask, DTE, IV,
  delta, gamma, theta, vega, volume, open interest, and score;
- classify each contract as `TRADE CANDIDATE`, `OBSERVE`, or `NO TRADE`;
- expose an option model surface for price and IV sensitivity;
- use Agent tasks and Agent Eval to make the workflow auditable;
- keep Live locked, with no broker key, account read, or order submission.

## Tonight Goal

Build the first reliable Options operating loop:

1. Dashboard opens on `Options`, not BTC/ETH.
2. `Run Options Scan` creates and runs a read-only `us_options_scan` task.
3. Agent Eval uses deterministic Options cases as the safety regression suite.
4. Risk page explains Options read-only status and Live lock.
5. Docs make Options the mainline and mark BTC/ETH as legacy.

## Delivered Baseline

- `GET /api/options/daily-candidates`
- `GET /api/options/chain`
- `GET /api/options/contract`
- `GET /api/options/eval/latest`
- `GET /api/options/model/surface`
- `GET /api/options/snapshots/latest`
- Agent task type: `us_options_scan`
- Agent tool: `us_options_scanner`
- Dashboard default view: `Options`
- Dashboard secondary views: `Agent`, `Risk`, `Legacy BTC/ETH`
- Safety boundary: no broker key, no order wiring, Live locked

## Immediate Next Work

1. Options data reliability
   - Persist latest options scan snapshots in SQLite.
   - Add timestamp/freshness labels per underlying and option chain.
   - Separate provider errors from scanner decisions so data outages do not look
     like strategy conclusions.

2. Daily stock scanner
   - Expand the default watchlist beyond ETFs and mega-cap tech.
   - Add price move, relative volume, liquidity, and event-risk filters.
   - Output the exact stock, preferred side, observation window, and reason.

3. Broker-style options view
   - Add expiration selector, strike ladder, calls/puts side-by-side, and Greeks.
   - Keep one selected contract as the source for Agent score and model surface.
   - Show spread, midpoint, DTE, IV rank, delta band, and liquidity blockers.

4. Agent evaluation
   - Keep `safety_core` deterministic and fixture-driven.
   - Require Options scan happy path, provider-unavailable handling, contract
     detail completeness, no default paper order, live-order block, and audit
     completeness.
   - Safety score must remain full score or the suite fails.

5. 3D model preparation
   - Keep the current 2D surface payload stable.
   - Add a frontend-ready schema for `underlying price x IV -> option value /
     PnL`.
   - Do not render a 3D trading decision until the model has documented
     assumptions and limitations.

## Acceptance Criteria

- `http://127.0.0.1:8001/` defaults to the Options page.
- The first viewport shows Options candidates, option chain, contract detail,
  model surface, Agent Eval score, and `Live Locked`.
- Agent Eval includes Options cases, not BTC market-review cases, as the main
  safety suite.
- `python -m btc_eth_15m agent eval run --suite safety_core` passes.
- `pytest tests/test_options_lab.py tests/test_agent_harness.py -q` passes.
- No API key is required or read.
- No Testnet or Live order endpoint is called.
