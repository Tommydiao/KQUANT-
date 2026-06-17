# Focused kquant Integration

kquant is now an Options-first local workbench: research by default, Alpaca
Paper options for manually confirmed rehearsal, and Live locked. The BTC/ETH
15m code remains in this repository as a legacy sandbox for historical review
and compatibility, but it should not receive new product work unless that work
is needed to archive, remove, or safely isolate it.

## Current Scope

- Market: liquid US equities and ETFs for options research.
- Workflow: daily momentum candidates, public option-chain reads, local
  Black-Scholes IV/Greeks estimates, Agent scoring, model surface payloads, and
  audit records, Pilot Journal checklist, and manually gated Alpaca Paper order
  intents.
- Dashboard goal: make Options the first screen and keep Agent Eval, provider
  errors, snapshot freshness, and `Live Locked` visible.
- Safety goal: signal/Agent code reads no broker key and cannot auto-submit
  orders; Alpaca Paper uses env-only keys and manual confirmation; no Testnet
  options order and no Live order submission.

## Useful Legacy Pieces

- Agent Harness task lifecycle, tool calls, risk checks, approvals, reports, and
  audit events.
- Local-first dashboard patterns and job/log visibility.
- Existing readiness gates and live-lock language.
- BTC/ETH research outputs as historical examples only.

## Do Not Import Or Rebuild Now

- Generic multi-asset platform abstractions.
- Live broker connectivity, live order routing, or real-money options execution.
- BTC/ETH strategy improvements as mainline product work.
- React/Vite rewrite of the console before the no-build static console is stable.

## Near-Term Direction

1. Keep `Options` as the default dashboard view.
2. Persist Options scan and chain snapshots in SQLite so provider outages are
   auditable and do not masquerade as strategy conclusions.
3. Keep Agent Eval fixture-driven and require full safety score.
4. Treat the React/Vite app as stale until the static console and APIs are
   stable on Windows.
5. Preserve research-only signal core, paper gating, and live-lock guarantees.
