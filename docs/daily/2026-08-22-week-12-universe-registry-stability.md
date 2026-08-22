# KQUANT v2 Week 12: Canonical Universe Registry Stability

Date: 2026-08-22  
Branch: `codex/kquant-v2-gap-analysis`  
Scope: close the Week 4 Data Trust read-boundary defect and repair the local
catalogue drift left by the previous runtime.

## 1. Objective And Completion

Completion: 100% of this repair slice.

- `/api/stocks/universe` no longer updates `stock_universe` rows when the UI
  switches between `default`, `all`, or another runtime view.
- Empty databases receive the static catalogue only through an explicit
  bootstrap at application startup or a backfill operator command.
- Existing catalogues, including locally curated additions, are not replaced
  by the static seed.
- A separate repair command can restore a known sealed Registry; it is never
  called implicitly by an HTTP request or startup.

## 2. Code, Schema, API, And UI Changes

- Added `ensure_stock_universe_catalog()` and
  `restore_universe_from_registry()` in `kquant/universe_registry.py`.
- Added `python -m kquant repair-universe-registry`, which verifies the target
  content hash and writes a redacted `audit_events` record.
- App startup and Longbridge backfill entry points now use explicit catalogue
  initialization; the universe GET path only persists its separate runtime
  membership snapshot.
- No schema version change, broker surface, account access, or order route was
  added. No frontend code was required for this backend consistency repair.

## 3. Data Coverage And Quality

The local database was repaired from the existing sealed Registry
`usr_eb0a628fbc333f57ea6c`:

| Metric | Result |
| --- | --- |
| Active canonical symbols | 296 |
| Current 1d / 1h coverage | 294/296 / 294/296 (99.32% / 99.32%) |
| Historical validation coverage | 99/296 (33.45%) |
| Latest aligned coverage run | `dcr_c1ee7b8265b8888511ae` |
| Longbridge quota state | locked by provider code `301607` |
| Manual recovery windows | 31 |

The 99/296 historical result remains below the model-entry threshold. No
dataset or model selection was promoted.

## 4. Tests And Browser Acceptance

- Targeted Universe/Data Trust/Dashboard regression: `20 passed`.
- Universe snapshot and repair regression: `5 passed`.
- Full Python regression after the repair-command addition: `231 passed`.
- Frontend tests: `2 passed`.
- React/Vite production build: passed; existing single-chunk size warning remains.
- Read-only route scan: passed, 100 routes, no account/position/order/broker
  path.
- `git diff --check`: passed.
- Browser at `http://127.0.0.1:8001/`: current API contract loaded, Longbridge
  closed status visible, Service Worker controlled, mobile 375px document
  width stayed at 360px with no horizontal overflow.
- HTTP consistency check: coverage remained `materialized` with the same
  Registry and coverage run before and after `/api/stocks/universe?universe=default`.

## 5. Technical Debt And Leakage Risks

- Longbridge historical quota `301607` still prevents the remaining historical
  backfill. The next calendar-month boundary only permits a fresh bounded
  preflight; it does not prove provider entitlement.
- Historical universe membership remains survivorship-limited before the first
  recorded snapshot.
- Model evidence is still insufficient for an OOS Gate: 99/296 eligible
  historical symbols and no completed Shadow Observation window.
- A future catalogue edit must use an explicit versioned import/repair path;
  silently editing `stock_universe` would create a new Registry and invalidate
  aligned coverage artifacts.

## 6. Model And Strategy Result

No new model or strategy result was generated. The repair only restores data
lineage. Current strategy and validation evidence remain unchanged and are
reported separately from prospective observations.

## 7. Go / No-Go

**NO_GO.** The Data Trust read boundary is now green, but the historical
coverage and forward-evidence gates are not. Theme Prediction, Leadership, and
Stock Quant model promotion remain blocked until the required PIT dataset and
OOS evidence exist.

## 8. Branch, Commit, And Rollback Point

- Branch: `codex/kquant-v2-gap-analysis`
- Rollback point before this repair slice: `81456bf`
- The local database repair is auditable through `audit_events` and is
  reversible by running the same command against another sealed Registry.
- This slice is ready for a dedicated commit after the final full regression;
  the final regression is now green.

## 9. Next Week

If the quota preflight becomes eligible, run one bounded Longbridge recovery
batch and record a new immutable coverage run. In parallel, prepare the Week 5
Theme Taxonomy migration without allowing today’s classifications or returns
to rewrite historical membership.
