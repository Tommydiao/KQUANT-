# KQUANT Unified Workspace UI V2

Date: 2026-09-14  
Frontend contract: `kquant-workspace-web-graphite-signal-v2`  
Gateway: `http://127.0.0.1:8020`

## Purpose

The unified workspace is the daily browser entry for Stocks, Options and Crypto. It changes navigation and presentation only: stock and Crypto runtimes, databases, strategy versions and execution boundaries remain isolated.

## Information architecture

All three workspaces use the same destinations:

| Destination | Stocks | Options | Crypto |
| --- | --- | --- | --- |
| Today | Current conclusion, actions and risks | Urgent plans and latest candidates | Current regime, plans and risks |
| Opportunities | Stock scan, universe and themes | Filtered opportunity list and detail | CEX and DEX/MEME discovery |
| Chart | Stock candles and drawing tools | Underlying chart | Asset chart |
| Plans | Manual research plan and validation | Watched, simulated and manual records | EVAL, Paper, Shadow and Roll plans |
| Review | Evidence, research, Journal and alerts | Outcomes, metrics and timeline | Evidence, research, Journal and alerts |
| Settings | Providers, coverage and diagnostics | OPRA, BBO, event and notification diagnostics | Providers, coverage and diagnostics |

Deep research opens as a contextual right drawer for Stocks and Crypto. Options keeps deterministic evidence in the opportunity detail and audit foldout.

## Option tracking contract

- An opportunity, plan and outcome have separate states.
- Watch state is not a fill.
- System simulation and user-reported outcomes are stored and reported separately.
- Missing fees never become zero-fee net performance.
- The original committed decision is immutable; later quote or state changes append timeline events.
- Watched plans and open outcomes continue to appear after the scan date changes.
- Strict simulated entry uses a qualifying ask after decision commit; strict exit uses a later bid.
- OPRA entitlement and a latest-trade timestamp do not by themselves prove strict BBO event time.

## URL compatibility

Canonical URLs preserve `workspace`, `view`, `symbol`, and optional option identifiers. The frontend accepts legacy `market` and page names (`discover`, `plan`, `research`, `journal`, `status`) and rewrites them to the canonical route. Full-stack startup also enables a legacy backend root redirect to port 8020; standalone backend startup does not.

Examples:

```text
/?workspace=stocks&view=opportunities&symbol=NVDA
/?workspace=options&view=opportunities&symbol=NVDA&opportunity=option-opportunity-id
/?workspace=crypto&view=plans&symbol=ETHUSDT
```

## Runbook

Build both affected frontends:

```powershell
cd C:\Users\Administrator\Desktop\KQUANT-\web
npm.cmd run build
npm.cmd run build:unified
```

Start only the unified Gateway without restarting existing backends:

```powershell
cd C:\Users\Administrator\Desktop\KQUANT-
.\start_kquant_workspace.ps1 -GatewayOnly -NoBrowser
```

### Current compatibility runtime

The validated 2026-09-14 session deliberately kept the pre-existing stock process on `8001` untouched. The unified Gateway on `8020` is currently connected to the new stock compatibility API on `8002` and KQUANT Crypto on `8011`; port `8010` belongs to an unrelated local application. These alternate ports are runtime compatibility choices, not a database or product merge. Use the launcher output for the actual upstream mapping and `/api/gateway/health` for availability and safety state.

Start a fresh full stack only during an approved maintenance window:

```powershell
.\start_kquant_workspace.ps1 -KillExisting -NoBrowser
```

The full-stack command restarts ports 8001, 8010 and 8020. It should not be used while a protected collector is running unless that restart is intentional.

## Safety boundary

The Gateway proxies only allowlisted research writes such as scan requests, watch state, manual research outcomes and simulations. It does not expose arbitrary broker, account, position or order routes. The UI remains research and manual-review software; UI completion is not evidence of option profitability.

## Delivery verification

- Stock Python regression: `253 passed`.
- Affected Gateway contract tests: `5 passed`.
- Unified workspace tests: `5 passed` across two files.
- Legacy and unified production builds: passed.
- Stock and Crypto read-only boundary scans: passed; option order submission remains disabled.
- Browser checks: Stocks, Options and Crypto navigation, mobile drawer, deep links and chart annotations passed.
- Responsive widths: `320`, `375`, `414`, `768` and `1243` pixels showed no page-level horizontal overflow.
- Live API smoke: Gateway, stock, Crypto, option status, radar, signals, data audit, watchlist and manual outcomes returned successfully.

The legacy build still reports its existing JavaScript bundle-size warning. The unified build is approximately 291 kB before gzip and does not emit that warning.
