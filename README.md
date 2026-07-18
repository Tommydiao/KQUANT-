# KQUANT US Stock Signal Terminal

KQUANT is being reset into a US stock-first research terminal.

The active product path is:

1. scan a curated Core 200 US stock/ETF universe;
2. judge long-only stock setups with five holding-period/risk profiles;
3. generate a read-only research plan with explicit data lineage and hard-veto reasons;
4. review 1H / 1D / 1W / 1M K-Lines before any manual decision;
5. add options later only as an expression layer for high-quality stock setups.

The system remains read-only. There is no broker account read, no paper order,
no live order, no testnet execution, and no automatic execution path. The AI
layer can rank research opportunities and generate entry/stop/target plans, but
a deterministic hard-veto layer blocks bad data, stale providers, risk-off
conditions, and every order/broker path.

## Current Phase

KQUANT was formally rebaselined to **Day 1 of the 84-day validation program**
on 2026-07-18. Product features are ahead of the evidence chain, so UI or AI
feature completeness does not count as a validated strategy or production
release.

- Canonical execution plan: [`docs/KQUANT_84_DAY_CODEX_PLAN.md`](docs/KQUANT_84_DAY_CODEX_PLAN.md)
- Current evidence-based audit: [`docs/current_system_audit.md`](docs/current_system_audit.md)
- Daily engineering logs: [`docs/daily/`](docs/daily/)

The current implementation inventory includes:

- new package namespace: `kquant`;
- new database: `work/kquant_us.sqlite3`;
- Core 200 default universe plus AI Five-Layer universe;
- Space / Robotics research layer available in `All` and search;
- one active validation strategy, `swing_long_v1`; additional profiles remain frozen legacy research modules;
- rule-based Action Conclusion Layer: `BUY`, `WAIT`, `DO_NOT_BUY`,
  `HOLD_TRAIL`, `EXIT_REVIEW`;
- AI Research Signal layer that ranks candidates and proposes entry, stop,
  target, risk/reward, and position-size hints under hard guardrails;
- API routes for stock universe, candles, provider health, and signal reports;
- React frontend refocused on `AI Today -> Search Stock -> Stock Detail ->
  K-Line -> AI Plan -> Journal`, with a consumer-style left navigation and
  explicit data reliability panel.

For the active 84-day program, only `swing_long_v1` is validated. Other
profiles, options, MSTR expansion, crypto, additional agents, and unrelated UI
expansion are frozen. They remain in the codebase but do not count as completed
roadmap work until their prerequisites pass.

## Product Direction: Consumer SaaS Preview

KQUANT is being shaped toward a future To C SaaS product, but the public
positioning is `AI Research Signal`, not investment advisory, managed trading,
or guaranteed performance.

Near-term local mode:

- local Python API at `http://127.0.0.1:8001/`;
- SQLite database at `work/kquant_us.sqlite3`;
- Longbridge read-only market data for intraday US quote and candle research;
- Yahoo/public candles as a clearly marked reference fallback only;
- OpenAI key stored only in the local backend environment.

Future SaaS target:

- Vercel frontend;
- hosted Python API;
- Postgres for user signals, journals, and scans;
- a formal market-data provider before any paid-user reliability commitment.

Payment, login, subscriptions, broker integrations, and order execution are not
enabled in this phase.

## Local Setup

```powershell
python -m venv .venv-win
.\.venv-win\Scripts\python -m pip install --upgrade pip
.\.venv-win\Scripts\python -m pip install -e ".[dev]"
```

Install the React frontend dependencies:

```powershell
cd web
npm install
```

## Run a Stock Signal Scan

The active 84-day validation path uses Longbridge as its primary read-only
market-data source. Yahoo public chart data is reference-only and can never
support a real-money BUY decision:

```powershell
python -m kquant stock-scan --source live --universe default --limit 20
```

Reports are written to:

- `outputs/stock-signals-report.json`
- `outputs/stock-signals-report.md`

Run a live data health scan when checking whether public candles are usable:

```powershell
python -m kquant stock-health --universes default,ai_five_layer --limit 20
```

Health reports are written to:

- `outputs/stock-live-data-health.json`
- `outputs/stock-live-data-health.md`

Run the MSTR cross-cycle bottom radar:

```powershell
python -m kquant mstr-cycle
```

MSTR radar reports are written to:

- `outputs/mstr-cycle-radar-report.json`
- `outputs/mstr-cycle-radar-report.md`

Runtime data is stored in:

- `work/kquant_us.sqlite3`

## Start the Local Terminal

Daily startup:

```powershell
.\KQUANT_START.cmd
```

The launcher restarts any stale `8001` backend, opens
`http://127.0.0.1:8001/`, and keeps the terminal window open for logs. The
daily launcher requires Longbridge, so it cannot silently fall back to Yahoo
reference data.

First-time Longbridge setup:

```powershell
.\KQUANT_SETUP_LONGBRIDGE.cmd
```

The setup securely prompts for the three Longbridge values, stores them in the
Windows user environment, and starts the dashboard with Longbridge required.
It never prints credentials. Revoke and replace any credential that has ever
appeared in a screenshot.

Realtime market-data check:

```powershell
.\KQUANT_REALTIME_CHECK.cmd
```

This checks the active provider, SDK, quote entitlement, current session,
realtime snapshot trust state, and the absence of account/order wiring.

First-time AI Review setup:

```powershell
.\setup_kquant_ai_key.ps1
```

This stores `OPENAI_API_KEY` in your Windows user environment, not in GitHub or
the frontend. Rotate the key if it has ever appeared in screenshots or chat.

Manual startup remains available. Use `-KillExisting` after a code, model-key,
or Longbridge configuration change:

```powershell
.\start_kquant_stock_terminal.ps1 -KillExisting -RequireLongbridge
```

Open `http://127.0.0.1:8001/`.

Monday pre-trade preflight:

```powershell
.\KQUANT_MONDAY_PREFLIGHT.cmd
```

Use this before any small-size manual-money pilot. It starts or reuses the
local backend, refreshes the AI Daily report, runs the readiness audit, opens
the dashboard, and writes the readiness files under `outputs/`.

Development verification:

```powershell
.\KQUANT_VERIFY.cmd
```

Use this before freezing code. It keeps the terminal open, runs the React
production build, the local readiness wrapper, and Python pytest when a usable
Windows Python environment is available.

## Monday Manual Money Pilot

The first real-money rollout is a small-size manual pilot. KQUANT can surface
AI-led research signals, entry/stop/target plans, and hard veto reasons, but
it still does not connect to a broker, read an account, or submit orders.

Run the one-click preflight before considering any real-money trade:

```powershell
.\KQUANT_MONDAY_PREFLIGHT.cmd
```

The preflight starts/reuses the local backend, refreshes the AI Daily report
when the backend key is available, then runs the readiness check. The readiness
check verifies:

- backend online at `http://127.0.0.1:8001/`;
- live data enabled and user-visible fixture data disabled;
- AI key available on the local backend;
- no broker, account, or order wiring;
- latest AI Daily report freshness;
- live daily and confirmation candles for `NVDA`, `RKLB`, and `MSTR`;
- no BUY bypass of the hard readiness gate.

It also writes an audit trail for the session:

- `outputs/monday-pilot-readiness.json`
- `outputs/monday-pilot-readiness.md`

Keep the latest readiness report with the day's journal so every manual-money
decision can be traced back to the live data, AI, and safety state that was
visible before trading.

If you only need to rerun the audit without refreshing AI Daily, the lower-level
PowerShell command remains available:

```powershell
.\check_kquant_monday_pilot.ps1
```

Pilot risk rules:

- trade stocks only; no options, no leveraged ETFs, no automatic execution;
- max account risk per trade: `0.25%`;
- first day max trades: `1-2`;
- total first-day risk: `0.5%`;
- no chasing, no averaging down, no trade during provider/data caution;
- every real-money candidate needs a journal note before entry;
- if readiness says `NO TRADE`, do not place a real-money trade.

Detailed runbook: `docs/monday_live_pilot_runbook.md`.

Printable checklist: `docs/monday_live_pilot_checklist.md`.

Run the full local verification wrapper before freezing a trading-day build:

```powershell
.\verify_kquant_local.ps1
```

It runs the React production build, the Monday readiness check, and Python
pytest when a usable Windows Python environment is available. If `.venv-win`
is broken, it prints the repair commands and exits with caution rather than
pretending the Python regression passed. Use `-Strict` when you want missing
pytest coverage to fail the verification.

## Protected Vercel Frontend + Cloudflare Access Backend

The Vercel deployment is a static React frontend. Real K-Lines require a
reachable Python backend. For a private deployed workflow, keep the backend on
this PC and expose it through Cloudflare Tunnel protected by Cloudflare Access:

> The Vercel URL is a display surface only. It must show `Live API offline`
> when the protected backend is unreachable, and cannot replace the local
> Longbridge backend for real-money research.

1. Create a named Cloudflare Tunnel and publish a hostname such as
   `kquant-api.example.com`.
2. Protect that hostname with a Cloudflare Access self-hosted application that
   only allows your email.
3. Set local environment variables:

```powershell
$env:KQUANT_CLOUDFLARE_HOSTNAME="kquant-api.example.com"
$env:KQUANT_CLOUDFLARE_TUNNEL_NAME="your-tunnel-name"
$env:OPENAI_API_KEY="sk-..."
```

4. Start the backend and tunnel:

```powershell
.\start_kquant_cloudflare_access.ps1
```

5. In Vercel, set the frontend build variable:

```text
VITE_KQUANT_API_BASE_URL=https://kquant-api.example.com
```

The OpenAI key stays on the backend only. Do not put `OPENAI_API_KEY` in Vercel
frontend variables, screenshots, or committed files.

## API Routes

The local Python dashboard exposes:

- `GET /api/stocks/universe?universe=default|ai|ai_five_layer|all`
- `GET /api/health`
- `GET /api/stocks/search?q=robot&universe=all`
- `GET /api/stocks/candles?symbol=NVDA&range=1y&interval=1d&source=live`
- `GET /api/stocks/quote?symbol=NVDA`
- `GET /api/stocks/realtime-snapshot?symbol=NVDA`
- `GET /api/stocks/market-data/status`
- `GET /api/stocks/market-data/self-check?symbol=NVDA`
- `GET /api/stocks/strategy-validation`
- `GET /api/stocks/signals?source=live&universe=ai_five_layer&profile=swing_long_v1`
- `GET /api/stocks/analyze?symbol=NVDA&source=live&profile=tactical_1w_v1`
- `POST /api/stocks/ai-review` (legacy review/commentary endpoint)
- `POST /api/stocks/ai-decision`
- `POST /api/stocks/ai-daily-agent`
- `GET /api/stocks/ai-review/status`
- `GET /api/stocks/ai-daily-report/latest`
- `GET /api/stocks/signals/latest`
- `GET /api/stocks/provider-health`
- `GET /api/stocks/live-data-health?universes=default,ai_five_layer&limit=20`
- `GET /api/stocks/live-data-health/latest`
- `GET /api/mstr/cycle-radar?source=live`

Each stock candle payload includes source, provider status, freshness, and
provider errors. Stock signal payloads include score breakdown, AI layer, and
manual exit-risk reminders. The AI Trading Agent can rank opportunities and
generate entry/stop/target plans, but a deterministic hard-veto layer blocks
AI buy candidates when live data, provider status, market regime, or exit-risk
guardrails fail. Broker, account, and order wiring remain disabled. Live
failures are surfaced as stale real cache, provider failed, or unavailable
status; the live path never silently mixes fixture candles. Internal fixture
helpers are reserved for deterministic tests.

The MSTR Cycle Radar uses MSTR and BTC-USD as live/reference market data, but
does not restore BTC/ETH trading as a product path. It is read-only and reports
`CYCLE ACCUMULATION`, `BOTTOM WATCH`, `WAIT`, or `DISTRIBUTION RISK`.
MSTR premium and financing proxies use the public Strategy tracker when
available, with a local stale-real-cache fallback in `work/mstr_reference_cache.json`.
The radar also exposes SaylorTracker/StrategyTracker-style monitoring metrics:
BTC holdings, NAV premium, mNAV, BTC NAV, market cap, enterprise value, cost
basis, unrealized P/L, sats/share, BTC Yield/Gain, debt/BTC NAV, ATM raise
proxy, liquidity, and benchmark performance. Metrics are calculated locally
where possible and explicitly marked when tracker fields are unavailable.
Its Monte Carlo layer estimates 6m/12m/24m return and drawdown scenarios, and
its Bayesian layer estimates bottom probability from interpretable evidence.
Both are read-only research aids; they do not override the cycle level or issue
buy/sell/order instructions.

## Frontend

```powershell
cd web
npm run dev
```

Open `http://127.0.0.1:5173/`.

The frontend supports:

- English / Chinese;
- Light / Dark theme;
- live-only real data guard with stale cache and provider failure states;
- TradingView-style 1H / 1D / 1W / 1M charts via `lightweight-charts`;
- Core 200, AI Five-Layer, and All universe views;
- Space / Robotics layer and command search for ticker, company, theme, or tag;
- search-driven single-stock analysis and four-system comparison;
- Live API status and AI Review status for protected deployment;
- AI-led daily research signals and per-stock AI Trading Command;
- Monday readiness panel and manual trade ticket with hard veto checks;
- selected stock review, signal reasons, risk warnings, and manual checklist;
- MSTR Cycle Radar with MSTR, BTC, MSTR/BTC relative charts, Monte Carlo
  scenarios, Bayesian bottom probability, and StrategyTracker Metrics;
- responsive mobile layout.

Build:

```powershell
cd web
npm run build
```

## Roadmap

The roadmap is documented in `docs/us_stock_roadmap.md`.

Short version:

- Phase 0: architecture reset and database cleanup.
- Phase 1: US stock data foundation.
- Phase 2: stock signal engine v1.
- Phase 3: formal React frontend.
- Phase 4: backtest and training labels.
- Phase 5: 10-trading-day live pilot.
- Phase 6: options return as ATM expression layer.
- Phase 7: read-only AI review assistant.

## Safety Policy

- AI can lead opportunity ranking and research-plan generation, but hard
  guardrails can veto any high-confidence buy candidate.
- First version is long-only.
- Default timeframes are daily trend and 1h confirmation.
- Options are not the first entry point.
- No automated execution path is allowed.
- AI outputs are research signals and manual trade plans, not broker orders.
- Human review, journal entry, and manual execution remain required.
