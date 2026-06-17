# kquant Runtime Check

Updated for the Windows Options-first continuation.

## Runtime

- Project root: `C:\Users\Administrator\Desktop\KQUANT\polymarket-btc-5min`.
- Current Windows Python baseline: `.venv-win` created with Python 3.12.10.
- Install command:

```powershell
python -m venv .venv-win
.\.venv-win\Scripts\python -m pip install --upgrade pip
.\.venv-win\Scripts\python -m pip install -e ".[dev]"
```

- Web dependency baseline:

```powershell
cd web
npm install
```

The checked-in `.venv` and `.venv-kquant` directories were copied from a macOS
environment and are not valid Windows runtimes. Do not use them for local
verification on this computer.

Git has been initialized locally. Runtime artifacts are excluded through
`.gitignore`, including `work/`, `outputs/`, SQLite/WAL files, `.venv-win/`,
`web/node_modules/`, and `web/dist/`.

## Verified Direction

- Product name: `kquant US Options Research Terminal`.
- Active workflow: US Options scan, option-chain view, contract scoring, model
  surface, SQLite Pilot Journal, manually gated Alpaca Paper order intents, Agent
  Eval, and audit trail.
- BTC/ETH remains a legacy sandbox and is not the active roadmap.
- Live remains locked. Alpaca Paper is the only options broker path and is
  paper-only.

## Current Baseline

- Agent `safety_core` was verified in a temporary DB at `100.0/100`.
- FastAPI app creation succeeds on Windows Python 3.12.
- Project SQLite state already contains Options Agent tasks, passing evals, and
  zero `paper_orders`.
- Latest public live Options scan can return `live_read_only_unavailable` when
  Yahoo/Nasdaq public endpoints time out. This is a provider state, not a
  strategy conclusion.

## Verification Commands

```powershell
.\.venv-win\Scripts\python -m pytest tests/test_options_lab.py tests/test_agent_harness.py tests/test_dashboard.py tests/test_options_broker.py -q
.\.venv-win\Scripts\python -m btc_eth_15m agent --db-path $env:TEMP\kquant-agent.sqlite3 --outputs-dir $env:TEMP\kquant-agent-outputs eval run --suite safety_core
.\.venv-win\Scripts\python -c "from btc_eth_15m.dashboard.app import create_app; create_app('config/default.yml')"
```

Run the local dashboard:

```powershell
.\.venv-win\Scripts\python -m btc_eth_15m dashboard --config config/default.yml --host 127.0.0.1 --port 8001
```

Open `http://127.0.0.1:8001/`.

## Remaining Watchpoints

- Public Yahoo/Nasdaq data can time out from this network. Check
  `/api/options/snapshots/latest?symbol=SPY` for the latest provider status and
  freshness before interpreting scanner output.
- The React/Vite app is not the primary console yet; the no-build static
  dashboard is the current delivery path.
- Alpaca Paper smoke should only hit real Alpaca endpoints when
  `ALPACA_PAPER_API_KEY` and `ALPACA_PAPER_SECRET_KEY` are explicitly set.
