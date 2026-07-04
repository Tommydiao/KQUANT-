# Local Development

This repo is currently optimized for a local single-user US Stock Signal
Terminal. The daily path is live-only stock research with Core 200, AI
Five-Layer, Space/Robotics, strategy profiles, K-line review, and manual
journaling. Options and BTC/ETH are not the main product path. Broker/account
access and paper/live/testnet orders remain disabled for the stock terminal.

## Python Environment

On this Windows machine, use `.venv-win` as the local development environment
(currently verified with Python 3.12.10):

```powershell
python -m venv .venv-win
.\.venv-win\Scripts\python -m pip install --upgrade pip
.\.venv-win\Scripts\python -m pip install -e ".[dev]"
```

If `.venv-win\Scripts\python.exe` prints `No Python at ...`, the virtual
environment points to a removed Python installation. Recreate it after
installing Python 3.12:

```powershell
Remove-Item -Recurse -Force .\.venv-win
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

Windows stock-terminal launcher:

Daily one-click startup:

```powershell
.\KQUANT_START.cmd
```

This restarts any stale `8001` backend, opens the browser, and keeps the log
window open. For manual startup without killing an existing backend:

```powershell
.\start_kquant_stock_terminal.ps1
```

Daily pre-trade verification:

```powershell
.\KQUANT_VERIFY.cmd
```

This keeps the terminal open while running the local verification wrapper. Use
it before any manual-money pilot so the READY / CAUTION / NO TRADE result and
the readiness audit files are visible without remembering the PowerShell
command.

Before any small-size manual real-money pilot, run the readiness check:

```powershell
.\check_kquant_monday_pilot.ps1
```

The script verifies live data, AI status, latest AI Daily report, representative
NVDA/RKLB/MSTR K-lines, and that broker/account/order wiring is still disabled.
Use `docs/monday_live_pilot_runbook.md` as the operating checklist.
Use `docs/monday_live_pilot_checklist.md` as the short printable checklist
before and during the first manual-money session.

The readiness script also writes:

- `outputs/monday-pilot-readiness.json`
- `outputs/monday-pilot-readiness.md`

These files are the pre-trade audit record for the day. If the status is
`NO_TRADE`, do not place a real-money trade. If the status is `CAUTION`, treat
the day as observation-only unless the warning is explicitly understood and
documented in the journal.

For a one-command local release check, run:

```powershell
.\verify_kquant_local.ps1
```

This wrapper runs `npm run build`, `check_kquant_monday_pilot.ps1`, and pytest
when a usable Python runtime exists. On machines where `.venv-win` points to a
removed Python install, it prints the venv repair commands and exits with
caution. Add `-Strict` to make a missing Python test runtime fail the check.

## AI Review Assistant

AI Review is a manual-trigger, read-only review layer. It can summarize risk,
ask review questions, and suggest R/R improvements, but it does not change the
rule score, does not trigger scans, and has no broker/order path.

Recommended first-time setup:

```powershell
.\setup_kquant_ai_key.ps1
```

This stores the key in the Windows user environment. New terminal windows and
`KQUANT_START.cmd` will pick it up automatically. You can still configure keys
only for the current PowerShell session if needed:

```powershell
$env:OPENAI_API_KEY="..."
$env:KQUANT_AI_REVIEW_MODEL="gpt-5.4"
$env:KQUANT_AI_BATCH_MODEL="gpt-5.4-mini"
$env:KQUANT_AI_DEEP_MODEL="gpt-5.5"
.\start_kquant_stock_terminal.ps1
```

Do not put `OPENAI_API_KEY` in `web/`, GitHub, Vercel frontend variables,
screenshots, reports, or committed config files.

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
