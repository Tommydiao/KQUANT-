# Runtime Check

1. Build the frontend with `npm.cmd run build` in `web`.
2. Run `python -m pytest -q`.
3. Run `python scripts/verify_read_only_boundary.py`.
4. Start `.\start_kquant_stock_terminal.ps1 -KillExisting -NoBrowser`.
5. Check `http://127.0.0.1:8001/api/health` and the market-data self-check.

The self-check must report route safety `pass`, credential values not exposed,
database write success, calendar status, and market-data entitlement state.
