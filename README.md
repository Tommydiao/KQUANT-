# KQUANT

KQUANT is a local, single-user US stock and ETF research terminal. It combines
read-only Longbridge market data, deterministic technical features, guided
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

### Optional Local Login

Create the local email identity, password hash, and signing secret without placing a
plaintext password in `.env`:

```powershell
.\.venv\Scripts\python -m kquant local-login-config
```

Set the printed `KQUANT_LOGIN_*` values in the private `.env` file, then restart the
terminal. Once enabled, all research APIs require the local browser session; neither
the email, password, nor password hash is returned by the API.

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
- `GET /api/stocks/analyze?symbol=NVDA&source=live&profile=swing_long_v1`
- `GET /api/stocks/RKLB/early-trend`
- `GET /api/instructions/current`
- `GET /api/alerts/stream`
- `GET /api/notifications/status`
- `POST /api/notifications/web-push/subscribe`
- `POST /api/stocks/ai-decision`
- `POST /api/stocks/strategy-validation/runs`
- `GET /api/stocks/strategy-validation/latest`
- `GET /api/stocks/strategy-validation/actions/{action}`

The realtime snapshot returns BBO, spread, UTC quote time, quote/bar age,
forming and closed 1m/5m bars, exchange-calendar state, and a trust label.

## Strategy Validation

Historical validation uses a deterministic, versioned action policy. Actual AI
outputs are tracked prospectively in a separate evidence chain and are never
mixed into historical statistics. The active canonical research strategy is
`swing_long_v1.1.0`. It can only be frozen for forward observation from a
reviewed validation fingerprint and Evidence Score; missing evidence remains
`NO_GO`, not a silent upgrade to production readiness.

```powershell
python -m kquant validate-strategies `
  --profiles tactical_1w_v1,high_beta_growth_v1,early_trend_3_15d_v1 `
  --universe default
```

Signals use closed bars only, enter no earlier than the next bar, apply costs
and gap handling, use conservative stop-first treatment, and split data 60/20/20
with a maximum-horizon embargo.

The early-trend strategy reports daily setup evidence separately from closed
1H/5m trigger evidence. It remains paper-only until the sealed validation and
prospective observation gates pass. See `docs/early_trend_strategy.md`.

For optional iPhone Home Screen notifications, generate local VAPID values with
`python -m kquant web-push-config`, then follow `docs/iphone_web_push.md`.

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

## Forward Observation And Release Gate

The Today workspace shows a `NO TRADE` state whenever data, operations, hard
vetoes, or forward-evidence gates are not clear. KQUANT includes a Decision
Ledger, forward pilot protocol, and cash-only paper simulation, but none of
them accesses an account or submits an order.

Use [the forward pilot protocol](docs/forward_pilot_protocol.md) and run the
Release Candidate check before a local release:

```powershell
.\scripts\verify_release_candidate.ps1
```

The full frozen scope and current day-by-day progress are tracked in
[`docs/KQUANT_84_DAY_CODEX_PLAN.md`](docs/KQUANT_84_DAY_CODEX_PLAN.md).
