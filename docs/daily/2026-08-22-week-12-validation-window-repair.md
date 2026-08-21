# KQUANT v2 Week 12 Gate Repair: Historical Validation Readiness

Date: 2026-08-22
Branch: `codex/kquant-v2-gap-analysis`
Scope: read-only data-quality diagnostics. No market-data fetch, broker,
account, position, order, or execution capability was added.

## 1. Objective and completion

Objective: explain the mismatch between high operational Longbridge coverage
and the much smaller Stock Quant historical dataset without weakening any
validation Gate.

Implementation completion: 100% for the diagnostic. Data expansion remains a
separate, controlled operational task.

## 2. Delivered changes

- Added `kquant/stock_quant_readiness.py`.
  - Separates current signal coverage from historical point-in-time validation
    coverage.
  - Requires the minimum daily and 1H confirmation bars to have been available
    before the validation window starts, and requires the series to extend to
    the end of that window.
  - Returns explicit missing-history reasons per symbol without fetching or
    writing data.
- Added `GET /api/quant/stocks/validation-readiness`.
- Extended the read-only Quant overview and the terminal validation card with
  historical validation coverage.
- Advanced the coordinated runtime contract to
  `kquant-api-2026-08-22-v2-oos-shadow-v3`.

## 3. Actual data finding

For the immutable dataset `stock-model0-lb-validation-100-v2`:

- Operational current-signal coverage: 293 / 296 symbols.
- Historical full-window coverage at the 2026-01-23 validation start: 2 / 296
  symbols, or 0.68%.
- Required 90% target: 267 symbols; current shortfall: 265 symbols.
- Materialized historical dataset: 1,282 items, 50 symbols, and 102 signal
  dates from 2026-01-23 through 2026-08-12.
- Main limiting reason: 292 symbols lack 20 closed Longbridge 1H bars available
  at the start of the validation window.

The old 99% number remains useful for current K-line display. It is not
sufficient evidence that the same symbols could have generated a historical
signal at the start of a sealed replay window.

## 4. Leakage controls

- A candle fetched today is not treated as if KQUANT had already observed it
  at a historical signal time.
- The readiness report uses closed bars and an explicit `available_at` cutoff.
- No historical labels, strategy parameters, or model thresholds were changed
  after inspecting the sealed test result.
- Historical data backfill, if performed next, must retain fetch/audit time and
  must be evaluated as provider history rather than prospective observation.

## 5. Repair path and Gate

1. Run a bounded Longbridge historical 1H backfill smoke test using the
   existing resumable queue; record provider limits and actual returned span.
2. If Longbridge supports the required range, backfill in rate-limited batches
   with checkpoints and immutable source audit metadata.
3. Build a new dataset version from the expanded history, keep the previous
   sealed dataset untouched, and rerun walk-forward validation without using
   the old sealed test set for selection.
4. If the provider cannot supply the required historical 1H range, retain
   `limited evidence`, narrow the model scope honestly, and collect genuine
   forward data instead.

Current decision: `NO_GO`. Shadow Observation remains blocked because Phase 5
performance and concentration Gates are not satisfied.

## 6. Verification

- Focused readiness, overview, and dashboard API tests: `17 passed`.
- Full Python regression: `210 passed in 262.33s`.
- Frontend unit tests: `2 passed`.
- TypeScript and Vite production build: passed. The existing single-chunk size
  warning remains non-blocking.
- Read-only boundary scan: passed with 100 registered routes and no broker,
  account, position, or order-submission route.
- Browser smoke: the current terminal displayed `Historical validation
  2/296 (0.68%)`; desktop and 375px mobile layouts had no horizontal overflow,
  the current API contract was loaded, and the browser console had zero errors.
