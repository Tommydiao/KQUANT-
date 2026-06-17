# Crypto AI Agent Harness

The Agent Harness is the control layer around kquant's US options research
workflow. It manages task lifecycle, tool execution, risk checks,
approvals, reports, and audit records. BTC/ETH tasks are legacy compatibility
paths, not the active product direction. The Harness does not auto-submit
Alpaca Paper orders.

## Local CLI

Create and run a read-only US options scan:

```bash
python -m btc_eth_15m agent task create \
  --type us_options_scan \
  --payload '{"symbols":["AAPL","NVDA","TSLA"],"strategy_id":"us-options-live-scanner","create_paper_order":false}'

python -m btc_eth_15m agent task run <task_id>
python -m btc_eth_15m agent task status <task_id>
python -m btc_eth_15m agent task events <task_id>
```

Run the deterministic Options safety evaluation:

```bash
python -m btc_eth_15m agent eval run --suite safety_core
```

Approvals:

```bash
python -m btc_eth_15m agent approvals pending
python -m btc_eth_15m agent approvals approve <approval_id> --reason "approved for paper review only"
python -m btc_eth_15m agent approvals reject <approval_id> --reason "risk too high"
```

Use `--db-path` to target a different SQLite file and `--outputs-dir` to target report output:

```bash
python -m btc_eth_15m agent --db-path work/market.sqlite3 --outputs-dir outputs task status <task_id>
```

## API Routes

The FastAPI dashboard exposes the same runtime. The stdlib fallback dashboard on
port `8001` also exposes these routes so the Harness can be validated when
FastAPI or native Python dependencies are unavailable:

```http
POST /api/agent/tasks
GET  /api/agent/tasks/{task_id}
GET  /api/agent/tasks/{task_id}/events
POST /api/agent/tasks/{task_id}/run
POST /api/agent/tasks/{task_id}/pause
POST /api/agent/tasks/{task_id}/resume
POST /api/agent/tasks/{task_id}/cancel

GET  /api/agent/approvals/pending
GET  /api/agent/approvals/{approval_id}
POST /api/agent/approvals/{approval_id}/approve
POST /api/agent/approvals/{approval_id}/reject

GET  /api/agent/audit/events?task_id=...
```

The API layer is intentionally thin. The CLI and API call the same `AgentRuntime`.

## Tools

MVP tools are registered through `ToolRegistry`:

- `mock_market_data`: legacy read-only mock OHLCV data, explicitly marked as mock.
- `live_market_data`: legacy public crypto ticker/freshness reader retained for
  compatibility only.
- `us_options_scanner`: reads public US equity momentum and public option-chain
  data, estimates IV/Greeks locally, and writes a read-only options report.
- `backtest`: writes a dry-run backtest record.
- `risk_check`: persists risk rule evaluation.
- `report`: writes Markdown and JSON task reports.
- `paper_trading`: creates a simulated paper order without exchange calls.

New tools should subclass `ToolBase`, define `permission_level`, expose `input_schema()`, and implement `execute()`.

## State

SQLite tables are created automatically in `work/market.sqlite3`:

- `agent_tasks`
- `tool_calls`
- `risk_checks`
- `approval_requests`
- `audit_events`
- `paper_orders`
- `backtest_results`
- `strategies`

This is SQLite first. A future PostgreSQL adapter should keep the `StateStore` method contract stable.

## Safety Notes

The Harness MVP has no broker/live order tool. High-risk tasks can create
approval requests, but an approval only records acknowledgement; it does not
execute a live order or trigger Alpaca Paper. Manual Alpaca Paper endpoints live
outside the Harness auto-execution loop and require a ready intent plus explicit
manual confirmation. See `docs/risk_controls.md` for the default live lock,
approval states, and paper-order boundary.
