# kquant Interview Private Deployment

This project is intended to run as a private local dashboard. Research is the
default mode, Alpaca Paper is gated by environment keys and manual confirmation,
and Live orders are disabled. For interview demos, keep it private through
Tailscale Serve instead of a public deployment.

## URLs

- Local machine: `http://127.0.0.1:8001/`
- Fixture demo: `http://127.0.0.1:8001/?optionsSource=fixture`
- Tailscale private URL: printed by `start_kquant_private_tailscale.ps1` after login

## Start Private Demo

From this project folder:

```powershell
.\start_kquant_private_tailscale.ps1
```

If Tailscale is not logged in, the script prints a Tailscale login URL. Open it, log in, then rerun the script.

After the private URL is printed, open it from any device logged in to the same Tailscale tailnet.

## Check Private Access

```powershell
.\check_kquant_private_access.ps1
```

Expected safety checks:

- Dashboard responds on `127.0.0.1:8001`
- Journal storage is writable
- Dashboard is bound to localhost
- Tailscale is running
- Tailscale Serve is configured
- Signal auto-order wiring is disabled
- Live order wiring is disabled
- Paper order flow requires manual confirmation

## Interview Demo Path

1. Open the live dashboard.
2. Explain that the signal core is research-only; Alpaca Paper is optional,
   manual, and paper-only.
3. Show `Pilot Today`, provider health, Data Caution, and LLM Core locked.
4. Show `Today's ATM Alerts` and explain `ATM ALERT / WATCH / PASS`.
5. Click one alert and walk through stock K-line, option K-line, contract detail, and journal.
6. Open the independent 3D Buy Lens as final review.
7. Mention that live public providers can rate-limit; fixture mode is available for stable demos.

## Security Boundary

Do not enable `tailscale funnel`.
Do not expose this dashboard through a public domain unless authentication is added first.
Do not enable public access, live orders, or testnet execution. Do not enter real
broker keys in demos; Alpaca Paper keys must remain local environment variables.
