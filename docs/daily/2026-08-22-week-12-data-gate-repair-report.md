# KQUANT v2 Week 12 Gate Repair Report: Longbridge Historical Coverage

Date: 2026-08-22
Branch: `codex/kquant-v2-gap-analysis`
Scope: read-only Longbridge market data, historical-replay integrity, and
operational controls. No broker, account, position, order, execution, or live
trading capability was added.

## 1. Objective and completion

Repair the false historical-coverage path before rebuilding any Stock Quant
dataset. The intended order remains:

`historical pagination -> point-in-time availability -> strict source policy -> bounded backfill -> coverage Gate -> sealed OOS rebuild`

Implementation completion for this repair: complete. Historical coverage Gate:
not complete, because the provider's current-month symbol quota has been
reached.

## 2. Delivered code and operational changes

- `2af66b5 feat(data): paginate longbridge historical candles`
  - Replaced the 1,000-row ceiling for 5-year daily / 2-year 1H history with
    date-based pagination on the persistent, quote-only Longbridge context.
- `baf86a5 fix(quant): enforce market bar availability in replay`
  - Introduced `market_bar_close_bound_v1`; feature, label, snapshot,
    readiness, validation, freeze, and shadow paths now share a closed-bar
    availability contract.
- `0ecdb75` and `936fab2`
  - Made both resumable and direct backfill entry points Longbridge-only.
  - Backfill workers explicitly load only the required local market-data
    variables and never fall back to Yahoo or load research-model keys.
- `cb61741`
  - Added the local monthly unique-symbol quota preflight and
    `python -m kquant backfill-quota-status`.
- `25cb8e6`
  - Separated full provider history, limited history, and genuine failure in
    the job audit.
- `1740962`
  - Turns Longbridge error `301607` into a calendar-month provider quota lock.
    Remaining queued work is marked `blocked_quota`; no retry loop or Yahoo
    fallback is allowed.

## 3. Controlled provider evidence

Successful Longbridge-only smoke:

- `SPY`, `QQQ`, and `NVDA`: 1,259 five-year daily candles and 3,500 two-year
  1H candles per symbol.
- A bounded 12-symbol core batch completed 24 / 24 items with
  `source=longbridge_candles`.
- A first 50-symbol batch completed 94 / 100 items; short-history symbols are
  now correctly classified rather than treated as source outages.
- A second 50-symbol batch reached the provider's real historical K-line
  threshold. Longbridge returned `301607` with `requested:100 / limit:100`.

KQUANT stopped after that definitive provider response. It did not submit
additional requests after the quota lock was established.

## 4. Data-quality change

| Metric | Before repair | Current |
| --- | ---: | ---: |
| Historical validation-window eligible symbols | 2 / 296 | 99 / 296 |
| Historical validation-window coverage | 0.68% | 33.45% |
| Target for the data Gate | 267 / 296 | 267 / 296 |
| Additional eligible symbols required | 265 | 168 |
| Longbridge current-month historical quota state | unknown | provider quota exhausted |

The remaining dominant reason is `confirmation_history_below_window_start`.
Several newer listings have genuine but limited history; that evidence stays
auditable and never counts as full 5-year / 2-year target coverage.

## 5. Leakage and source controls

- A historical bar becomes eligible only after its conservative market
  close-bound `available_at`, while later `fetched_at` remains an audit fact.
- Yahoo rows created by the earlier failed smoke remain legacy reference data;
  they are excluded from eligible snapshots, modeling, validation, and manual
  trading qualification.
- A stale Longbridge cache, a forming bar, a provider quota block, or missing
  history cannot become a buy-class signal.
- Existing sealed v1 validation evidence remains immutable but cannot satisfy
  the current-contract freeze or Shadow Observation gate.

## 6. Verification

- Focused queue, quota, local-environment, and data-trust tests: passed.
- Full Python regression: `224 passed in 265.55s`.
- Frontend unit tests: `2 passed`.
- TypeScript and Vite production build: passed. The existing 545 KB initial
  chunk warning remains non-blocking.
- Read-only boundary scan: passed with 100 registered routes; no broker,
  account, position, or order-submission route.
- Browser smoke after restart: API contract v4 loaded, Longbridge Live was
  visible, no console errors were recorded, and the 375 px mobile viewport had
  no horizontal overflow.

## 7. Gate and next action

Decision: `NO_GO`.

The Week 4 data coverage Gate is not met, so KQUANT must not rebuild the
sealed Stock Quant dataset, select a predictive model, or start Shadow
Observation from this partial history. The current-month repair is complete.

At the next Longbridge calendar-month reset, first run:

```powershell
python -m kquant backfill-quota-status --db-path work\kquant_us.sqlite3
```

Only after it reports `ready` should the resumable queue continue with the
remaining `confirmation_history_below_window_start` symbols. Recheck the
99/296 coverage after every bounded batch. Once 267 eligible symbols are
available, build a new sealed current-contract dataset and rerun OOS validation
without modifying the previous test partition.
