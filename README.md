# KQUANT US Stock Signal Terminal

KQUANT is being reset into a US stock-first research terminal.

The active product path is:

1. scan a curated 100-stock US universe;
2. judge long-only stock setups with daily trend plus 1h confirmation;
3. output `BUY SETUP`, `WATCH`, or `PASS`;
4. review daily and 1h K-Lines before any manual decision;
5. add options later only as an expression layer for high-quality stock setups.

The system remains read-only. There is no broker account read, no paper order,
no live order, no testnet execution, and no LLM in the signal core.

## Current Phase

The current implementation starts Phase 0-2 of the roadmap:

- new package namespace: `kquant`;
- new database: `work/kquant_us.sqlite3`;
- selected 100-stock universe;
- `swing_long_v1` long-only stock signal profile;
- API routes for stock universe, candles, provider health, and signal reports;
- React frontend refocused on `Today's Stock Setups`, daily K-Line, 1h K-Line,
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

Runtime data is stored in:

- `work/kquant_us.sqlite3`

## Start the Local Terminal

```powershell
.\start_kquant_stock_terminal.ps1
```

Open `http://127.0.0.1:8001/`.

## API Routes

The local Python dashboard exposes:

- `GET /api/stocks/universe?universe=default|ai|ai_five_layer|all`
- `GET /api/stocks/candles?symbol=NVDA&range=1y&interval=1d&source=live`
- `GET /api/stocks/signals?source=live&universe=ai_five_layer&profile=swing_long_v1`
- `GET /api/stocks/signals/latest`
- `GET /api/stocks/provider-health`
- `GET /api/stocks/live-data-health?universes=default,ai_five_layer&limit=20`

Each stock candle payload includes source, provider status, freshness, and
provider errors. Stock signal payloads include score breakdown, AI layer, and
manual exit-risk reminders. Live failures are surfaced as stale real cache,
provider failed, or unavailable status; the live path never silently mixes
fixture candles. Internal fixture helpers are reserved for deterministic tests.

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
- TradingView-style daily and 1h charts via `lightweight-charts`;
- selected stock review, signal reasons, risk warnings, and manual checklist;
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
