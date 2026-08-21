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

## Current evidence

The local audit for August 2026 is:

| Field | Value |
| --- | --- |
| Provider quota state | `provider_quota_exhausted` |
| Provider error code | `301607` |
| Locally tracked symbols | 296 |
| Local configured cap | 100 |
| Next safe action | Recheck eligibility after 2026-09-01 00:00 UTC |

The provider-side remaining balance is intentionally reported as unknown.
The calendar boundary only clears KQUANT's local lock; the next bounded
preflight must still confirm the provider's actual entitlement before any
historical request is made.

## Verification

- Data Trust, backfill queue, quota, and dashboard regression tests: `28 passed`.
- New tests cover the calendar boundary, provider-code redaction-safe state,
  coverage route inclusion, and the read-only contract.
- Final full regression after the UI and cache changes: Python `227 passed`,
  frontend tests `2 passed`, production build passed, and the read-only route
  scan passed with 100 routes and no broker, account, position, or order route.
- Browser verification loaded the new content-hash bundle, showed both coverage
  layers and the quota lock, recorded no new console error, and had no mobile
  horizontal overflow at 375 px.

## Gate

Decision: `NO_GO`.

Historical validation-window coverage remains 99 / 296 symbols (33.45%), below
the 267 / 296 Data Trust requirement. No sealed OOS rebuild, predictive-model
selection, or Shadow Observation start is permitted until coverage reaches the
required threshold and the subsequent validation gates pass.
