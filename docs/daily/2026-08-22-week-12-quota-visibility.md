# KQUANT v2 Week 12: Longbridge Quota Visibility

Date: 2026-08-22
Branch: `codex/kquant-v2-gap-analysis`
Scope: read-only Data Trust observability only. This change makes no market
data request, does not create a model run, and adds no broker or execution
surface.

## Delivered

- Extracted the Longbridge historical-symbol quota audit into
  `kquant/market_data_quota.py`, so the backfill worker and Data Trust report
  read the same local evidence.
- `GET /api/data/coverage` and the compatible stock coverage route now include
  `backfill_quota`: current calendar month, local tracked symbol count, quota
  lock, provider response code when known, and a next-month *recheck* time.
- The Settings Data Trust card and the Today v2 evidence overview now say when
  historical backfill is paused by a provider quota lock. The UI explicitly
  states that KQUANT will not automatically send a request when the date is
  reached.
- The Data Trust route now separates current operational K-line coverage from
  full historical validation-window coverage. A high current-coverage number
  cannot be mistaken for permission to rebuild a Stock Quant dataset.
- Corrected the local PWA cache contract: HTML, manifest, Service Worker, and
  unversioned assets are always revalidated; only Vite content-hash assets are
  cacheable. This prevents a restarted local server from silently serving an
  old frontend bundle.
- Added `resume-quota-backfill`, an explicit cross-month recovery command. It
  clones only items with a persisted `301607` quota proof into a new queue;
  the source job stays immutable, no provider request is made by the recovery
  command, and a separate bounded run remains an operator action.
- Split Data Trust delivery into a fast materialized `detail=summary` view and
  the backward-compatible default full audit. The summary reads the latest immutable coverage run
  only when its universe registry still matches; otherwise it safely falls
  back to a live aggregation. Full per-symbol gap analysis remains available
  for audit and is never silently truncated.
- Market breadth is intentionally not calculated inside the coverage-summary
  hot path. It is a separate all-history input and is reported as unloaded
  until a dedicated breadth snapshot is available; KQUANT never substitutes a
  stale breadth number as current model evidence.
- Recovery candidates are idempotent: once a source job has a recovery child,
  it is removed from the manual candidate list and cannot be cloned again.

## Current evidence

The local audit for August 2026 is:

| Field | Value |
| --- | --- |
| Provider quota state | `provider_quota_exhausted` |
| Provider error code | `301607` |
| Locally tracked symbols | 296 |
| Local configured cap | 100 |
| Next safe action | Recheck eligibility after 2026-09-01 00:00 UTC |
| Manual recovery candidates | 2 source jobs / 31 time windows |
| Latest aligned coverage snapshot | 2026-08-21T21:55:17Z |

The provider-side remaining balance is intentionally reported as unknown.
The calendar boundary only clears KQUANT's local lock; the next bounded
preflight must still confirm the provider's actual entitlement before any
historical request is made.

## Manual recovery sequence

After the calendar boundary, run the local audit first:

```powershell
python -m kquant backfill-quota-status --db-path work\kquant_us.sqlite3
```

Only when its `status` is `ready`, choose a `source_job_id` from
`quota_recovery.candidates` and create a replacement queue:

```powershell
python -m kquant resume-quota-backfill `
  --source-job-id <source_job_id> `
  --db-path work\kquant_us.sqlite3
```

That command does not fetch data. Review its new `job_id`, then explicitly run
one bounded batch with `python -m kquant run-market-backfill --job-id <job_id>`.
Recheck coverage after every batch. Do not use the recovery command while the
quota audit is locked.

## Verification

- Data Trust, backfill queue, quota, dashboard, and summary-snapshot
  regression tests: `33 passed`.
- New tests cover the calendar boundary, provider-code redaction-safe state,
  coverage route inclusion, and the read-only contract.
- Final full regression after the UI and cache changes: Python `227 passed`,
  frontend tests `2 passed`, production build passed, and the read-only route
  scan passed with 100 routes and no broker, account, position, or order route.
- Browser verification loaded the new content-hash bundle, showed both coverage
  layers and the quota lock, recorded no new console error, and had no mobile
  horizontal overflow at 375 px.
- Quota-recovery regression verifies that a legacy `failed` item containing
  `301607` is recovered only after a new calendar-month preflight, that only
  the quota-blocked interval is copied, and that the recovery operation makes
  no market-data request.
- Final regression for this repair: Python `228 passed`, frontend tests
  `2 passed`, production build passed, and the read-only route scan passed
  with 100 registered routes and no broker, account, position, or order route.
- Fresh-server browser smoke loaded the current versioned bundle. The Settings
  Data Trust card showed the materialized 99.32% current 1d/1h coverage,
  historical validation 99/296, provider error `301607`, and 31 manually
  recoverable windows. The mobile document width stayed within its viewport
  and the fresh navigation recorded no console errors.

## Gate

Decision: `NO_GO`.

Historical validation-window coverage remains 99 / 296 symbols (33.45%), below
the 267 / 296 Data Trust requirement. No sealed OOS rebuild, predictive-model
selection, or Shadow Observation start is permitted until coverage reaches the
required threshold and the subsequent validation gates pass.
