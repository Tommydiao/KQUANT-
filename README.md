# KQUANT

KQUANT is a read-only research workspace with one unified browser workspace and
two isolated market runtimes behind it:

| Runtime | Scope | Direct fallback URL | Source directory |
| --- | --- | --- | --- |
| KQUANT US Stocks | Longbridge stock/ETF market data, transparent factors, strategy validation, journal and manual research | http://127.0.0.1:8001/ | repository root |
| KQUANT CRYPTO | CEX, DEX and MEME monitoring, EVAL Agent review, Paper/Shadow research and alerts | http://127.0.0.1:8010/ | [`crypto/`](crypto/) |

The normal browser entry is the unified workspace at
http://127.0.0.1:8020/. It owns one login session, lets you switch between
Stocks and Crypto, and keeps the two databases, providers and strategy
versions separate. The 8001 and 8010 URLs are local fallback/debug entries.

The stock project stays at the repository root so its existing Windows launchers,
Vercel configuration and local paths remain compatible. The crypto project is a
separate Python package, database, frontend and runtime under `crypto/`; it does
not import the stock package or share runtime data.

## Safety Boundary

Both terminals are research-only:

- no exchange or broker account access;
- no wallet, private-key or signing access;
- no holdings, positions or order submission endpoints;
- no automatic trading;
- provider credentials, login material and notification secrets are environment-only;
- forming candles, stale data, unknown security data and failed evidence gates fail closed.

The Crypto EVAL Agent is the final deterministic review layer for crypto trade
plan drafts. LLM output is advisory and cannot change an EVAL decision, alter
Entry/Stop/Target, bypass a security blocker or send an alert directly.

## US Stock Terminal

Start both runtimes and the unified UI from the repository root:

```powershell
.\KQUANT_START.cmd
```

Open [http://127.0.0.1:8020/](http://127.0.0.1:8020/). To restart an existing
local session, run `powershell -ExecutionPolicy Bypass -File
.\start_kquant_workspace.ps1 -KillExisting`.

Run from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
cd web
npm.cmd ci
npm.cmd run build
cd ..
.\start_kquant_stock_terminal.ps1 -KillExisting
```
Open [http://127.0.0.1:8001/](http://127.0.0.1:8001/).

The stock terminal uses Longbridge for read-only market data. Yahoo is retained
only as reference history and cannot satisfy a buy-class data gate. Detailed
stock operations remain in [`docs/US_STOCK_README.md`](docs/US_STOCK_README.md).

## Crypto Terminal

Run from `crypto/`:

```powershell
cd crypto
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m kquant_crypto db migrate
.\.venv\Scripts\python.exe -m pytest -q
cd web
npm.cmd ci
npm.cmd run build
cd ..
.\start_kquant_crypto.ps1 -KillExisting
```

Open [http://127.0.0.1:8010/](http://127.0.0.1:8010/). This is the latest local
Crypto website; it is reachable on this computer while the Crypto dashboard is
running. No public hosted Crypto URL is claimed by this repository yet.

The current Crypto foundation includes public CEX market ingestion, closed-candle
storage, Data Trust, market regime, transparent factors, DEX/MEME discovery,
security snapshots, Paper cost estimation, validation and the deterministic EVAL
review chain. The release authority remains closed by default. See
[`crypto/README.md`](crypto/README.md) and
[`crypto/docs/daily/2026-08-23-validation-and-collection-gates.md`](crypto/docs/daily/2026-08-23-validation-and-collection-gates.md)
for the latest evidence and remaining gates.

## Verification

```powershell
# US stock project
python -m pytest -q
cd web
npm.cmd test -- --run
npm.cmd run build
cd ..
python scripts/verify_read_only_boundary.py

# Crypto project
cd crypto
python -m pytest -q
cd web
npm.cmd test -- --run
npm.cmd run build
cd ..
python scripts/verify_read_only_boundary.py
```

GitHub Actions runs both suites without real credentials. Runtime databases,
Parquet data, `outputs/`, `work/`, `.env` files, virtual environments and
frontend build output are excluded from version control.

## Repository Layout

```text
KQUANT-/
├─ kquant/, web/, tests/, docs/, scripts/     # US stock terminal
├─ crypto/                                    # independent Crypto terminal
├─ .github/workflows/ci.yml                   # stock + crypto CI
└─ README.md                                  # this project index
```
