# KQUANT v2 Week 11 Addendum: Multi-fold OOS Hardening

Date: 2026-08-22
Branch: `codex/kquant-v2-gap-analysis`
Scope: read-only Stock Quant validation only. No broker, account, position,
order, or execution capability was added.

## 1. Goal and completion

Goal: replace the previous single chronological holdout interpretation with a
genuine, expanding-window, purged multi-fold OOS check and prevent a model
from looking deployable when it fails evidence gates.

Implementation completion: 100%.

Research / Shadow gate: NO_GO.

## 2. Delivered changes

- `kquant/quant_dataset.py`
  - Added `rolling_purged_oos_folds()` with three chronological folds,
    expanding training history, date-based partitions, label-end-time purge,
    and a five-trading-day embargo on both boundaries.
  - Separates true label-overlap purge counts from ordinary future-held-out and
    embargo exclusions so the audit does not mislabel withheld future data as
    leakage removal.
- `kquant/stock_quant_validation.py`
  - Runs every Model 0 / Logistic candidate through local train and validation
    selection for each OOS fold. The permanently sealed final test partition is
    not supplied to the fold runner.
  - Applies the same sample-size, bootstrap mean-R, Profit Factor, and maximum
    drawdown thresholds to the aggregate rolling-OOS evidence.
  - Separates `selected_model_by_train_validation` from `deployment_model`.
    A final-test or rolling-OOS failure yields `deployment_model = null`; it
    cannot select a different model using test performance.
  - Records `deployment_status` and explicit `deployment_blockers` in the
    immutable validation summary.
- `kquant/v2_overview.py` and
  `web/src/components/QuantOverviewPanel.tsx`
  - Expose a research candidate separately from a deployable model.
  - The terminal now says "No deployable model" until every gate passes rather
    than presenting a validation-only candidate as active.
- `web/public/service-worker.js`, `web/src/main.tsx`,
  `kquant/dashboard/app.py`, and `start_kquant_stock_terminal.ps1`
  - Replaced the stale app-shell cache with an assets-only cache for content
    hashed JavaScript and CSS files. The unversioned HTML entry point, manifest,
    icon, and every API request are always fetched from the network.
  - Service Worker registration now bypasses HTTP cache during update checks;
    health and startup-script contract versions were advanced together.
- Tests
  - Added multi-fold label-boundary checks and explicit no-deployment coverage
    for a NO_GO validation report.

No schema migration was needed: validation summaries are immutable JSON stored
in the existing v11 validation tables.

## 3. Data coverage and quality

Current canonical Longbridge coverage remains above the Week 4 model gate:

- Daily: 293 / 296 eligible symbols (98.99%).
- 1H: 294 / 296 eligible symbols (99.32%).
- 1m: 3 / 296; it is not a required input for this historical Stock Quant run.
- Yahoo observations remain `legacy_reference` and are rejected by the
  dataset builder.

The new sealed validation dataset is
`stock-model0-lb-validation-100-v2`: 1,282 point-in-time rows across 50
Longbridge-only symbols. Its currently available 1H timeline starts on
2026-01-23 and ends on 2026-08-12. The pre-sealed-test history provides 84
distinct signal dates, just enough for three five-day-embargo folds. This is
enough for an integrity check, not enough evidence to claim broad market
robustness.

## 4. Historical evidence (not live performance)

Validation chose `logistic` using only train and validation data. Its sealed
test subset contains 25 selected trades, so it fails the required 100-trade
minimum even though its single final holdout metrics look favorable.

| Model | Final selected test trades | Final average R | Final PF | Final max DD | Aggregate 3-fold OOS average R | Aggregate 3-fold OOS PF | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Model 0 rule | 144 | +0.10065R | 1.33179 | 11.29433R | +0.07010R | 1.22294 | NO_GO |
| Logistic | 25 | +0.35139R | 3.34870 | 1.39238R | -0.02036R | 0.93925 | NO_GO |

Model 0 also has a negative bootstrap lower bound on mean R and drawdown above
the 8R limit. Logistic has a positive final-holdout lower bound, but its
three-fold OOS aggregate has a negative bootstrap lower bound, PF below 1.25,
and drawdown above 8R. These are historical model diagnostics only; they are
not a live win rate, an execution claim, or a recommendation.

## 5. Leakage and technical-debt register

- The expanding folds use only pre-sealed-test history, but the available 1H
  history is still short and covers only one recent market regime range.
- Corporate actions and earnings-event calendar data are still incomplete.
  Event-risk coverage must be filled or explicitly stratified before any later
  widening of the universe.
- The current dataset has 50 symbols, not the full 296-symbol universe. It is
  a controlled validation slice, not a final production cohort.
- LightGBM and Quantile remain unavailable in the current environment and are
  reported as unavailable rather than substituted with Logistic results.
- The data capture process must continue accumulating genuine forward results;
  simulated dates may never count toward the 20-day Shadow requirement.

## 6. Verification

- Focused Python regression: `10 passed`.
- Full Python regression: `201 passed in 261.08s`.
- Frontend unit tests: `2 passed`.
- TypeScript and Vite production build: passed; the pre-existing single chunk
  size warning remains.
- Read-only boundary scan: passed with 99 registered routes and no forbidden
  broker/account/position/order route.
- Browser smoke: desktop and 375px mobile widths had no horizontal overflow;
  the visible terminal displayed both the research candidate and "No deployable
  model" with zero console errors. A forced Service Worker update then loaded
  the current content-hashed JavaScript bundle and showed the readable blockers
  "independent test trades below 100" and "multi-fold OOS evidence is not
  stable".

## 7. Go / No-Go

- Go: multi-fold OOS integrity implementation, fail-closed deployment state,
  regression suite, frontend build, and local browser verification.
- No-Go: Shadow activation and any live-money interpretation.

The latest immutable validation summary has:

- `selected_model_by_train_validation = logistic`
- `deployment_model = null`
- `deployment_status = no_eligible_model`
- `deployment_blockers = [minimum_test_trades, walk_forward_stability]`

## 8. Rollback and next work

Rollback point before this slice: `2a71cfd`.

Week 12 remains in progress. The next work is operational rather than another
parameter search: complete the release-audit surface, preserve the NO_GO state,
and begin only genuine 20-trading-day Shadow Observation once the frozen
strategy evidence gate is satisfied. No options engine or execution route is
part of this work.
