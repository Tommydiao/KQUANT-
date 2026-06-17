# kquant Next Goal: ATM Options Live Pilot

## Goal

The current goal is to run kquant as a local ATM Options workbench for 3 US
trading days. The platform should help with manual option review: find ATM
alerts, inspect stock and option K-Lines, confirm liquidity, open the 3D Buy
Lens, record a Pilot Journal note, and optionally rehearse a manually confirmed
Alpaca Paper options order. This is live public-data observation and paper-only
execution rehearsal, not real-money execution.

## Scope

In scope:

- US equities and ETF underlyings such as `SPY`, `QQQ`, `NVDA`, `TSLA`, `AAPL`,
  `MSFT`, `AMD`, `META`, `AVGO`, and `AMZN`.
- Public read-only underlying and option-chain data.
- Broker-style option-chain display with expiration, strike, bid/ask, midpoint,
  spread, volume, open interest, DTE, IV, delta, gamma, theta, and vega.
- Agent task type `us_options_scan`.
- Agent Eval for task lifecycle, tool calls, report completeness, audit
  completeness, no default paper order, and live/high-risk blocking.
- Option model surface for `underlying price x implied volatility` sensitivity.
- 3-trading-day Live Pilot journal entries: `reviewed`, `skipped`, and
  `paper-observed`.
- SQLite-backed Pilot Journal with legacy JSON import/mirror compatibility.
- Alpaca Paper options adapter for manually confirmed single-leg long options.
- Pilot status API for Day 1/2/3, Default 50 scan, AI Watchlist scan, provider
  errors, journal coverage, and locked LLM/order safety flags.
- Cache-first live dashboard behavior, with manual scans to reduce public
  provider rate-limit pressure.

Out of scope:

- BTC/ETH strategy improvement.
- Broker key storage, live account reads, live positions, live order preview, or
  live order submission.
- Short options, spreads, or market live orders.
- Real-money execution.
- LLM-based trade recommendations or signal scoring.
- Any external AI model call inside `alert_score`, `ATM ALERT/WATCH/PASS`, scan
  triggering, broker/order workflows, or execution gates.

## Work Plan

1. Product direction lock
   - Keep `Options` as the default Dashboard tab.
   - Keep BTC/ETH visible only under `Legacy BTC/ETH`.
   - Keep all safety labels explicit: `research-only signal core`, `Alpaca
     Paper gated`, `Live Locked`.

2. Agent scan loop
   - Run `us_options_scan` from CLI and Dashboard.
   - Write `outputs/options-worthiness-report.md` and `.json`.
   - Store task, tool call, risk check, and audit events in SQLite.

3. Agent Eval v2 baseline
   - Require `us_options_scan_happy_path`.
   - Require `us_options_scan_provider_unavailable`.
   - Require `us_options_contract_detail`.
   - Require `default_no_paper_order`.
   - Require `live_order_blocked`.
   - Require `audit_completeness`.

4. Options data and display
   - Show daily stocks and their scan reason.
   - Show one selected option chain with expiration tabs.
   - Show selected contract detail and model surface.
   - Surface provider errors without turning them into trade conclusions.

5. Model surface foundation
   - Keep 2D model data stable for future 3D rendering.
   - Include assumptions and limitations in every model response.
   - Treat the model as sensitivity analysis, not a recommendation engine.

6. Live Pilot and AI policy
   - Run Default 50 and AI Watchlist manually once per trading day.
   - Use `/api/options/live-pilot/status` as the single status surface for
     Pilot Today UI and daily review checks.
   - Keep provider degraded, stale snapshot, and empty option candles under
     `Data Caution`.
   - Require journal checklist coverage for stock K-Line, option K-Line, and 3D
     Buy Lens before treating an observation as complete.
   - Keep the LLM signal core locked during the pilot.
   - Allow a future AI Review Assistant only as read-only commentary after pilot
     quality is stable.

7. Alpaca Paper rehearsal
   - Use `GET /api/broker/options/status` before any paper workflow.
   - Require complete contract detail and Pilot Journal checklist.
   - Create `POST /api/options/order-intents` with `manual_confirmed=true`.
   - Submit `POST /api/options/paper-orders` only after a second manual confirm.
   - Persist every intent/order/cancel as an audit event.

## Done Criteria

- `pytest tests/test_options_lab.py tests/test_agent_harness.py tests/test_dashboard.py tests/test_options_broker.py -q` passes.
- `python -m btc_eth_15m agent eval run --suite safety_core` passes and reports
  Options cases.
- Dashboard at `http://127.0.0.1:8001/` defaults to Options and shows
  `Live Locked`.
- Dashboard shows `LLM Core Locked` and does not call an external AI model for
  signal generation.
- Browser has no horizontal overflow and no JavaScript console errors.
- Signal/Agent code cannot auto-create orders.
- Alpaca Paper order flow is limit-only, manually confirmed, and auditable.
- No code path places live orders.
