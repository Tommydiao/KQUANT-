# Local Development

## Setup

```powershell
python -m pip install -e ".[dev]"
cd web
npm.cmd ci
npm.cmd run build
cd ..
```

Start the combined API and built frontend:

```powershell
python -m kquant.dashboard --host 127.0.0.1 --port 8001
```

For Vite development, run `npm.cmd run dev` in `web`; `/api` proxies to port 8000.

## Validation

```powershell
python -m pytest -q
python scripts/verify_read_only_boundary.py
python -m kquant validate-strategies --profiles tactical_1w_v1,high_beta_growth_v1
```

Tests must use mocks for Longbridge and AI. A real-data smoke is manual and only
runs when fresh environment credentials have been explicitly configured.
