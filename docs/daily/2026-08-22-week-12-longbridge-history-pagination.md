# KQUANT v2 Week 12 Gate Repair: Longbridge Historical Pagination

Date: 2026-08-22
Branch: `codex/kquant-v2-gap-analysis`
Scope: read-only Longbridge historical market-data retrieval. No broker,
account, position, order, or execution capability was added.

## Objective

Repair the false historical-coverage result caused by the standard Longbridge
candlestick endpoint's maximum of 1,000 rows per request. The existing
backfill requested 3,500 two-year 1H bars but received only the latest 1,000,
which was enough for the operational display but not enough for a sealed
historical validation window.

## Delivered change

- Added `LongbridgeReadOnlyRuntime.history_candlesticks_by_date()` to the
  existing persistent quote-only context.
- `longbridge_candles()` now selects date-based historical pagination whenever
  the requested bar count exceeds 1,000.
- Each page is normalized, de-duplicated by UTC opening time, and fetched from
  the latest page backwards until the requested date window is covered.
- Historical results report `delivery_mode=history_by_date`,
  `freshness=historical_backfill`, and explicit pagination metadata. They are
  intentionally not represented as live quote data.
- The five-year daily range now requests the normal 1,260 trading-day target.
- Advanced the resumable queue marker to `longbridge_backfill_v1.2.0`.

## Read-only provider verification

Using the configured Longbridge quote credentials, without writing to SQLite:

- `AAPL`, `2y`, `1h`: 3,500 candles across four pages, from
  2024-08-19 through 2026-08-21.
- `AAPL`, `5y`, `1d`: 1,259 provider candles across two pages, from
  2021-08-17 through 2026-08-21. The one-bar difference from the nominal
  1,260 target reflects the provider's actual trading-calendar history.

## Leakage and operational controls

- The adapter uses the persistent `QuoteContext` only. It never initializes a
  Longbridge trade context.
- Historical pagination carries a separate freshness state, so a chart or
  strategy cannot mistake backfilled history for a current quote.
- Yahoo remains outside this path; a Longbridge failure is still handled by
  the existing explicit reference-data policy.
- A full-universe run is not started by this code change. The existing
  restart-safe queue must first run bounded batches and retain provider result
  metadata, limits, and failures.
- Follow-up repair: resumable backfill jobs explicitly load only missing
  Longbridge market-data settings from the local `.env` through
  `kquant.local_env`. They never load research-model credentials, never expose
  values in their audit payload, and fail before a candle request when the
  Longbridge credentials are absent. Backfill calls also disable Yahoo
  reference fallback, so a failed Longbridge job cannot write fallback rows as
  fresh backfill data.
- The older direct `run_longbridge_backfill` operational entry point now uses
  the same strict configuration and no-fallback policy as the resumable queue.
- KQUANT now records a local calendar-month unique-symbol ledger before any
  new backfill job. The default safety cap is 100 symbols, the documented
  minimum Longbridge tier. It blocks new symbols above that cap but permits
  resume work for symbols already audited in the same month. The provider's
  actual remaining quota is not exposed to KQUANT, so a higher verified tier
  must be configured explicitly through
  `KQUANT_LONGBRIDGE_MONTHLY_SYMBOL_CAP` (bounded to the documented 3,000
  maximum). Use `python -m kquant backfill-quota-status` before widening a
  batch; all backfill CLI commands load only the market-data allowlist rather
  than the full local `.env`.
- Queue audit now distinguishes `completed` (target history reached),
  `completed_limited` (genuine Longbridge history persisted but below the
  requested five-year daily or two-year 1H target), and `failed` (no usable
  Longbridge result). Limited history never counts as full coverage or as a
  validation-Gate pass, but it is not misreported as a provider outage.
- A real Longbridge `301607` response now creates a calendar-month provider
  quota lock. The triggering item and every remaining queued item are marked
  `blocked_quota`, the job terminates without retries, and new jobs are denied
  until the next calendar month. This was exercised on 2026-08-21 after the
  provider reported `requested:100 / limit:100`; no further historical
  requests are made by KQUANT in that month.

## Verification

- New quote-runtime confinement test: passed.
- New multi-page/de-duplication/freshness test: passed.
- Real provider read-only range checks: passed as documented above.

## Gate status

The historical range capability is now available, but the Stock Quant
historical coverage and Phase 5 release Gate remain `NO_GO` until controlled
backfill, immutable dataset rebuilding, and fresh walk-forward validation are
complete.
