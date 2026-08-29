# KQUANT US Stock Terminal

This document preserves the detailed operating notes for the stock project.
The stock source code remains at the repository root for backwards-compatible
launchers and deployment configuration.

KQUANT is a local, single-user US stock and ETF research terminal. It combines
read-only Longbridge market data, deterministic technical features, guided
manual review, a journal, and reproducible strategy validation.

## Safety Boundary

- Market data only. The runtime creates a Longbridge `QuoteContext` and never a trade context.
- No account, holdings, broker, execution, or derivative-order endpoints.
- Yahoo data is display/reference fallback only and hard-vetoes buy-class actions.
- Forming candles may update charts but never confirm rules, actions, or backtests.
- Research explanations cannot execute a trade.

Run the boundary audit:

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

Optional environment variables are read from the private `.env` file by the
Windows launcher:

```text
KQUANT_MARKET_DATA_PROVIDER=longbridge
LONGBRIDGE_APP_KEY=...
LONGBRIDGE_APP_SECRET=...
LONGBRIDGE_ACCESS_TOKEN=...
OPENAI_API_KEY=...
```

Values are never returned by health/self-check APIs. Rotate a credential before
using realtime mode if it has appeared in a screenshot, log or shared file.

## Main APIs

- `GET /api/health`
- `GET /api/stocks/realtime-snapshot?symbol=NVDA`
- `GET /api/stocks/analyze?symbol=NVDA&source=live&profile=swing_long_v1`
- `GET /api/stocks/RKLB/early-trend`
- `GET /api/instructions/current`
- `GET /api/alerts/stream`
- `GET /api/notifications/status`
- `POST /api/stocks/strategy-validation/runs`
- `GET /api/stocks/strategy-validation/latest`

The realtime snapshot returns BBO, spread, UTC quote time, quote/bar age,
forming and closed 1m/5m bars, exchange-calendar state and a trust label.

## Strategy Validation

Historical validation uses deterministic, versioned action policies. Actual
research-model outputs are tracked prospectively in a separate evidence chain
and are never mixed into historical statistics. The active canonical strategy is
`swing_long_v1.1.0`; missing evidence remains `NO_GO`.

Signals use closed bars only, enter no earlier than the next bar, apply costs and
gap handling, use conservative stop-first treatment, and split data 60/20/20
with a maximum-horizon embargo. Early-trend evidence separates daily setup from
closed 1H/5m trigger evidence.

## Verification

```powershell
python -m pytest -q
cd web
npm.cmd test -- --run
npm.cmd run build
cd ..
python scripts/verify_read_only_boundary.py
```

The full development scope is tracked in
[`docs/KQUANT_84_DAY_CODEX_PLAN.md`](KQUANT_84_DAY_CODEX_PLAN.md).
