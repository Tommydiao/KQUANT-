# KQUANT US Stock Signal Terminal

KQUANT is being reset into a US stock-first research terminal.

The active product path is:

1. scan a curated Core 200 US stock/ETF universe;
2. judge long-only stock setups with four holding-period profiles;
3. output `BUY SETUP`, `WATCH`, or `PASS`, plus a manual trading conclusion;
4. review 1H / 1D / 1W / 1M K-Lines before any manual decision;
5. add options later only as an expression layer for high-quality stock setups.

The system remains read-only. There is no broker account read, no paper order,
no live order, no testnet execution, and no LLM in the signal core. The optional
AI Review Assistant is manual-trigger commentary only.

## Current Phase

The current implementation starts Phase 0-2 of the roadmap:

- new package namespace: `kquant`;
- new database: `work/kquant_us.sqlite3`;
- Core 200 default universe plus AI Five-Layer universe;
- Space / Robotics research layer available in `All` and search;
- four long-only strategy profiles for 1W, 1-2M, 6M, and 1-3Y holding periods;
- rule-based Action Conclusion Layer: `BUY`, `WAIT`, `DO_NOT_BUY`,
  `HOLD_TRAIL`, `EXIT_REVIEW`;
- manual-trigger AI Review Assistant that cannot change score, level, or action;
- API routes for stock universe, candles, provider health, and signal reports;
- React frontend refocused on `Today's Stock Setups`, stock K-Lines,
  signal reasons, risk warnings, and manual checklist.

Options are intentionally secondary until the stock signal workflow is stable.

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

The user-facing stock terminal is live-only. It uses public Yahoo chart data
and must be treated as provider-limited:

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

```powershell
.\start_kquant_stock_terminal.ps1
```

Open `http://127.0.0.1:8001/`.

## Protected Vercel Frontend + Cloudflare Access Backend

The Vercel deployment is a static React frontend. Real K-Lines require a
reachable Python backend. For a private deployed workflow, keep the backend on
this PC and expose it through Cloudflare Tunnel protected by Cloudflare Access:

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
- `GET /api/stocks/signals?source=live&universe=ai_five_layer&profile=swing_long_v1`
- `GET /api/stocks/analyze?symbol=NVDA&source=live&profile=tactical_1w_v1`
- `POST /api/stocks/ai-review`
- `GET /api/stocks/ai-review/status`
- `GET /api/stocks/signals/latest`
- `GET /api/stocks/provider-health`
- `GET /api/stocks/live-data-health?universes=default,ai_five_layer&limit=20`
- `GET /api/stocks/live-data-health/latest`
- `GET /api/mstr/cycle-radar?source=live`

Each stock candle payload includes source, provider status, freshness, and
provider errors. Stock signal payloads include score breakdown, AI layer, and
manual exit-risk reminders. Live failures are surfaced as stale real cache,
provider failed, or unavailable status; the live path never silently mixes
fixture candles. Internal fixture helpers are reserved for deterministic tests.

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
- manual trading conclusion and manual-trigger AI Review panel;
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

- Core signals are rule-based, not LLM-scored.
- First version is long-only.
- Default timeframes are daily trend and 1h confirmation.
- Options are not the first entry point.
- No automated execution path is allowed.
- Any future AI assistant can only explain, summarize, and organize review notes.
