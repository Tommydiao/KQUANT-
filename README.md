# KQUANT

KQUANT is a local, single-user US stock and ETF research terminal. It combines
read-only Longbridge market data, deterministic technical features, AI-assisted
manual review, a journal, and reproducible strategy validation.

## Safety Boundary

- Market data only. The runtime creates a Longbridge `QuoteContext` and never a trade context.
- No account, holdings, broker, execution, or derivative-order endpoints.
- Yahoo data is display/reference fallback only and hard-vetoes buy-class AI actions.
- Forming candles may update charts but never confirm rules, AI actions, or backtests.
- AI ranks and explains research candidates; it cannot execute a trade.

Run the boundary audit at any time:

```powershell
python scripts/verify_read_only_boundary.py
```

## Local Start

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
cd web
npm.cmd ci
npm.cmd run build
cd ..
.\start_kquant_stock_terminal.ps1 -KillExisting
```

Open `http://127.0.0.1:8001/`.

Optional environment variables are read from `.env` by the Windows launcher:

```text
KQUANT_MARKET_DATA_PROVIDER=longbridge
LONGBRIDGE_APP_KEY=...
LONGBRIDGE_APP_SECRET=...
LONGBRIDGE_ACCESS_TOKEN=...
OPENAI_API_KEY=...
```

Values are never returned by health/self-check APIs. Rotate a credential before
using realtime mode if it has appeared in a screenshot, log, or shared file.

## Main APIs

- `GET /api/health`
- `GET /api/stocks/realtime-snapshot?symbol=NVDA`
- `GET /api/stocks/analyze?symbol=NVDA&source=live&profile=tactical_1w_v1`
- `POST /api/stocks/ai-decision`
- `POST /api/stocks/strategy-validation/runs`
- `GET /api/stocks/strategy-validation/latest`
- `GET /api/stocks/strategy-validation/actions/{action}`

The realtime snapshot returns BBO, spread, UTC quote time, quote/bar age,
forming and closed 1m/5m bars, exchange-calendar state, and a trust label.

## Strategy Validation

Historical validation uses a deterministic, versioned action policy. Actual AI
outputs are tracked prospectively in a separate evidence chain and are never
mixed into historical statistics.

```powershell
python -m kquant validate-strategies `
  --profiles tactical_1w_v1,high_beta_growth_v1 `
  --universe default
```

Signals use closed bars only, enter no earlier than the next bar, apply costs
and gap handling, use conservative stop-first treatment, and split data 60/20/20
with a maximum-horizon embargo.

## Verification

```powershell
python -m pytest -q
cd web
npm.cmd run build
cd ..
python scripts/verify_read_only_boundary.py
```

Or use the Windows verification entry point after the environment is installed:

```powershell
.\scripts\verify_all.ps1
```

GitHub Actions runs the same checks on Windows without real credentials.
