# Local Development

This repo is currently optimized for a local single-user US options workbench:
research is default, Alpaca Paper options is the only broker adapter, and Live
orders remain locked. BTC/ETH commands remain available only for legacy
research reference.

## Python Environment

On this Windows machine, use `.venv-win` as the local development environment
(currently verified with Python 3.12.10):

```powershell
python -m venv .venv-win
.\.venv-win\Scripts\python -m pip install --upgrade pip
.\.venv-win\Scripts\python -m pip install -e ".[dev]"
```

The copied `.venv` and `.venv-kquant` directories are legacy macOS virtual
environments and should not be used for Windows verification.

Use the Windows environment for focused tests:

```bash
.\.venv-win\Scripts\python -m pytest tests/test_agent_harness.py -q
```

If native packages are unstable on a future machine, the Agent Harness core can
still be tested with system Python because it is stdlib-only:

```bash
/usr/bin/python3 -m pytest tests/test_agent_harness.py -q
```

## Agent Harness CLI

Create and run a read-only US options scan:

```bash
python -m btc_eth_15m agent task create \
  --type us_options_scan \
  --payload '{"symbols":["SPY","QQQ","NVDA","TSLA","AAPL"],"strategy_id":"local-options-dev","create_paper_order":false}'

python -m btc_eth_15m agent task run <task_id>
python -m btc_eth_15m agent task status <task_id>
python -m btc_eth_15m agent task events <task_id>
```

Run the deterministic Options safety eval:

```bash
python -m btc_eth_15m agent eval run --suite safety_core
```

Use a temporary SQLite database for experiments:

```bash
python -m btc_eth_15m agent \
  --db-path /tmp/kquant-agent.sqlite3 \
  --outputs-dir /tmp/kquant-agent-outputs \
  task create --type us_options_scan --payload '{"symbols":["SPY"],"source":"fixture","create_paper_order":false}'
```

## Dashboard APIs

FastAPI dashboard:

```bash
python -m btc_eth_15m dashboard --config config/default.yml --host 127.0.0.1 --port 8000
```

Stdlib fallback dashboard:

```bash
python -m btc_eth_15m.dashboard.stdlib_server --host 127.0.0.1 --port 8001
```

Both expose the Agent Harness API routes under `/api/agent/...`. The fallback server still rejects non-Harness state-changing dashboard actions, but allows local Harness task and approval operations because they only write SQLite audit/task state and do not call exchange APIs.

Options scan and chain responses also persist SQLite snapshots. Inspect the
latest provider status and freshness with:

```bash
curl -s "http://127.0.0.1:8001/api/options/snapshots/latest?symbol=SPY"
```

Pilot Journal entries are stored in SQLite at the configured `db_path` and
mirrored to `outputs/options-pilot-journal.json` for older tooling.

## API Smoke Test

```bash
curl -s -X POST http://127.0.0.1:8001/api/agent/tasks \
  -H 'content-type: application/json' \
  -d '{"type":"us_options_scan","payload":{"symbols":["SPY","QQQ"],"source":"fixture","create_paper_order":false}}'

curl -s -X POST http://127.0.0.1:8001/api/agent/tasks/<task_id>/run
curl -s http://127.0.0.1:8001/api/agent/tasks/<task_id>/events
```

## Alpaca Paper Options

The paper broker path is explicit and manually gated:

```powershell
$env:ALPACA_PAPER_API_KEY="..."
$env:ALPACA_PAPER_SECRET_KEY="..."
$env:ALPACA_PAPER_BASE_URL="https://paper-api.alpaca.markets"
```

Useful local checks:

```bash
curl -s http://127.0.0.1:8001/api/broker/options/status
curl -s http://127.0.0.1:8001/api/broker/options/account
curl -s http://127.0.0.1:8001/api/broker/options/positions
```

Create `/api/options/order-intents` only after selecting a contract and
completing the Pilot Journal checklist. `/api/options/paper-orders` requires an
intent id and a second `manual_confirmed=true`. Live orders are not implemented.

## Secrets

Do not paste API keys into chat, reports, tests, or screenshots. Alpaca Paper
keys are read from environment variables only; they are not written to SQLite or
reports.
