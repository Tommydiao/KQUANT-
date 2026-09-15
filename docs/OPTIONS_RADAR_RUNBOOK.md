# KQUANT Options Radar Runbook

## Runtime contract

- Policy: `option_radar_v1.1.0`
- Database schema: v15 (daily runtime and reviewed option-only calendars)
- Premarket run: 08:30 America/New_York on valid US trading days
- Earliest intraday confirmation: 09:40 America/New_York
- Execution: manual only
- Simulation: one contract, strict post-decision ask entry and later bid exit
- Order submission: disabled and not implemented

When explicitly enabled in the deployed service, the existing application supervisor runs the schedule. It catches up once after 08:30 ET and before market close. The catch-up checkpoint stores the actual start, never a backdated 08:30 decision. Intraday reviews use persistent five-minute checkpoints. A failed daily attempt remains visible; it does not block monitoring existing plans. Manual rescans are separate versioned jobs.

As of the 2026-09-15 implementation, the running compatibility backend is still disabled pending approval to restart. New static settings show the runtime and device subscriptions, but this is not proof the backend supervisor is enabled.

## CLI

Run from the repository root with the stock virtual environment:

```powershell
.\.venv\Scripts\python.exe -m kquant options-radar --action audit
.\.venv\Scripts\python.exe -m kquant options-radar --action status
.\.venv\Scripts\python.exe -m kquant options-radar --action premarket
.\.venv\Scripts\python.exe -m kquant options-radar --action intraday
.\.venv\Scripts\python.exe -m kquant options-radar --action latest
.\.venv\Scripts\python.exe -m kquant options-radar --action report
```

`premarket` and `intraday` use public/read-only market data and persist research evidence. They never submit an order.

## API

```text
GET  /api/options/radar/status
GET  /api/options/radar/premarket
POST /api/options/radar/runs
GET  /api/options/radar/jobs/{job_id}
GET  /api/options/signals/current
GET  /api/options/signals/{opportunity_id}
GET  /api/options/data-audit
GET  /api/options/research-report
GET  /api/options/watchlist
POST /api/options/watchlist
DELETE /api/options/watchlist/{plan_id}
GET  /api/options/plans/{plan_id}/timeline
GET  /api/options/manual-outcomes
POST /api/options/manual-outcomes
GET  /api/options/simulations
POST /api/options/simulations
```

The simulation POST accepts `observe`, `open`, or `close`. `open` and `close` fetch fresh quote evidence themselves; arbitrary client-supplied fill prices are rejected. Manual outcomes are stored separately from simulations. A completed manual result without explicit fees keeps gross P/L but leaves net P/L unavailable.

## States

```text
PREMARKET_WATCH
WAIT_OPEN_CONFIRMATION
QUOTE_BLOCKED
CONFIRMED
CANCELLED
INVALIDATED
EXIT_REVIEW
```

No opportunity is a valid simulated fill unless the contract has a native-timestamp, two-sided BBO received after the final intraday decision, its event and receipt clocks agree within 15 seconds, it satisfies the group spread limit, has both-side size, and passes Delta/OI/volume and event gates.

Provider timestamps more than 30 seconds ahead of local receipt remain a data conflict, not proof of a wrong Windows clock. Verify the raw SDK timezone, units, receipt time and an independent clock before proposing correction. Do not widen tolerance, rewrite old evidence, or change the system clock without approval. Depth and PushDepth in SDK 4.4.1 expose no native event timestamp. Receipt-only evidence cannot confirm a simulated fill.

## Recovery

Runs, opportunities, plans, quote evidence, and outcomes are immutable or material-state deduplicated in `work/kquant_us.sqlite3`. State changes are appended to `option_state_events`; the original decision timestamp is not overwritten by quote refreshes. Active watched plans and open outcomes remain visible across trading dates. Restarting the service reloads current state and cannot create a second simulated outcome for the same plan.

## Unified workspace

Build and start only the gateway while leaving existing stock and Crypto services untouched:

```powershell
cd web
npm.cmd run build:unified
cd ..
.\start_kquant_workspace.ps1 -GatewayOnly -NoBrowser
```

Open `http://127.0.0.1:8020/?workspace=options&view=opportunities`. By default the stock and Crypto services remain on ports 8001 and 8010. During the protected 2026-09-14 compatibility run, the Gateway uses stock API port 8002 and Crypto port 8011 because the existing 8001 process was not restarted and 8010 belongs to another local application. The launcher prints the actual upstream mapping; `/api/gateway/health` confirms availability and the safety boundary. A full-stack launch may enable legacy-root redirects to the unified workspace; standalone backend launches keep their fallback UI.

Before schema recovery, restore a verified SQLite backup. The backup created for this delivery is recorded under `work/backups/` and excludes secrets.

## Daily-runtime increment: 2026-09-15

Working directory: `C:\Users\Administrator\Desktop\KQUANT-`.
Interpreter: `.\.venv\Scripts\python.exe`. Existing listeners remain untouched: stocks 8001/8002, Crypto compatibility 8011, gateway 8020. Do not use `-KillExisting` or launch a second stack to enable the option watcher.

After approval and a checked deployment, the stock application's existing supervisor should be the sole owner. For a separately approved standalone process, use the SAME database and no additional OS scheduler:

```powershell
$env:KQUANT_OPTION_RADAR_ENABLED = "true"
.\.venv\Scripts\python.exe -m kquant options-radar --action serve --db-path work/kquant_us.sqlite3
```

Stop that foreground process with Ctrl+C. Do not terminate other Python processes. `status` reports persistent workers, task checkpoints and heartbeat age. The OS lock prevents a second new-version supervisor from owning the same database; it cannot coordinate an older binary that predates this lock. Reloading the browser does not enable the service.

For an isolated, bounded real-market smoke test (already verified):

```powershell
.\.venv\Scripts\python.exe scripts/probe_option_daily_cycle.py --output work/option_daily_probe_NEW_ID
.\.venv\Scripts\python.exe -m kquant options-radar --action intraday --db-path work/option_daily_probe_NEW_ID/probe.sqlite3
.\.venv\Scripts\python.exe -m kquant options-radar --action report --db-path work/option_daily_probe_NEW_ID/probe.sqlite3
```

The output directory must not exist. This is an explicitly MANUAL isolated cycle using real market data, not proof of a continuous daily service. Its evidence and outbox must not be merged into the production ledger or dispatched as current alerts.

Reviewed calendar import:

```powershell
.\.venv\Scripts\python.exe -m kquant options-radar --action import-calendar --calendar-file work/reviewed-calendar.json --db-path work/kquant_us.sqlite3
```

One JSON record covers one symbol/category. Required: `symbol`, `category` (`earnings`, `dividends`, `corporate`, `macro`), HTTPS `source_url`, SHA256 `source_hash`, `reviewer`, `review_status=reviewed`, timezone-aware `coverage_start`, `coverage_end`, `available_at`, `reviewed_at`, `valid_until`, and `events`. Macro uses symbol `*`. Each event includes `name`, `start_at`, `end_at`, and explicit `blocks_entry`. An empty list additionally requires `no_events_confirmed=true` backed by reviewed source coverage, not an unverified assumption. The importer validates the contract, not the truth or completeness of the source. New records are append-only and future/expired reviews fail closed. Default coverage spans seven days conservatively. Stock strategy event gates are unchanged.

Phone: open the protected HTTPS unified site on the iPhone, add it to the Home Screen, and use Options / Settings / Enable notifications on this device. Authorization and lock-screen verification require the user. No Cloudflare process or verified protected external hostname was established in this increment; do not publish the current unauthenticated local configuration.

Notification routes through the gateway start with `/api/stocks/notifications/`. Only user clicks request permission or send test pushes. All alerts persist before fan-out; the delivery worker does network IO separately from scanning and deadline monitoring. Post-delivery crash ambiguity is not an exactly-once guarantee at the phone; stable tags and persisted successful attempts prevent ordinary repeats.

The boundary verifier now creates a temporary database. Its previous default-app behavior applied v15 to the main database at `2026-09-15T13:46:32.106950Z`. No service restart occurred. The verified `work/backups/kquant-us-20260915T135003Z.sqlite3` is a POST-v15 recovery point, not a pre-migration rollback point. See the daily progress report before any restore.
