# KQUANT v2 Twelve-Week Reconciliation

Date: 2026-08-22  
Branch: `codex/kquant-v2-gap-analysis`  
Latest code commit: `2152389 fix(v2): invalidate stale downstream research lineage`

This report reconciles the twelve-week KQUANT v2 plan with the code, database,
current APIs, regression suite, and browser runtime. It separates implementation
completion from research evidence. A completed implementation Gate does not mean
that a model has predictive value or that the product is ready for live trading.

## 1. Executive Status

The dependency chain is implemented through the read-only research surface:

`Architecture Audit -> Data Trust -> Capital Rotation -> Theme -> Leadership -> Stock Quant`

Current status:

| Area | Current state | Gate |
| --- | --- | --- |
| Architecture audit and gap analysis | Repository and runtime inventory recorded | GO |
| Schema migration and audit | Versioned migrations, fingerprints, recovery checks | GO |
| Point-in-time data contract | Snapshot, availability, forming-bar and survivorship boundaries | GO |
| Data Trust and coverage | Current Longbridge daily/1H aggregation aligned to Registry | GO for runtime coverage; NO-GO for historical model coverage |
| Theme Taxonomy v1 | 294/296 symbols mapped, 2 explicit review items | GO |
| Capital Rotation v0.1 | Current Longbridge run, PIT and stress audit | GO for deterministic baseline |
| Dataset/model infrastructure | Sealed datasets, split, embargo, artifact registry | GO for infrastructure |
| Theme Prediction | Contract and fail-closed display exist; no qualifying OOS evidence | NO-GO |
| Leadership | Fresh lineage-aligned descriptive snapshot | GO for implementation; NO-GO for predictive performance |
| Stock Quant Model 0 | Feature/label/dataset/validation kernel exists | GO for implementation; NO-GO for deployment |
| Stock Quant OOS | Multi-fold checks exist, but gates fail | NO-GO |
| Product integration and PWA | Read-only evidence workbench, mobile layout, API/version checks | GO for release surface |
| Shadow Observation | No completed forward observation window | NO-GO |
| Live trading | No account, broker, position, order or automatic execution route | Intentionally unavailable |

Overall research and trading decision: **NO_GO**.

## 2. Data And Runtime Snapshot

The current API is served by a healthy local FastAPI process. The latest
runtime identifiers should be read from `/api/health` rather than copied into a
frontend constant. The current Registry is:

- Registry: `usr_eb0a628fbc333f57ea6c`
- Registry members: 296
- Primary provider: Longbridge, market-data-only
- Current daily Longbridge eligibility: 294/296, 99.32%
- Current 1H Longbridge eligibility: 294/296, 99.32%
- Current 1m Longbridge eligibility: 3/296, 1.01%; 1m is not required by the
  current historical model gate
- Canonical validation-eligible symbols in the current coverage response: 293
- Historical validation coverage: 99/296, 33.45%; 168 more symbols are needed
  to reach the 90% historical target
- Event calendar: `not_ingested`, therefore not trade eligible
- Market breadth: available from cached Longbridge daily candles, but explicitly
  marked incomplete until all symbols have a complete breadth series
- Longbridge historical backfill: provider quota code `301607`; recovery is
  locked until 2026-09-01
- Yahoo: retained as `legacy_reference`; it is not eligible for the canonical
  validation dataset, current signal qualification, or a current Longbridge
  research conclusion

The coverage API also exposes detailed candle source, adjustment mode, first and
last timestamps, fetch time, gaps, and event-data status per symbol. Current
coverage is sufficient to exercise the runtime path, but not sufficient to claim
that the historical model universe is complete.

## 3. Week-by-Week Reconciliation

### Week 1: Architecture Audit And Unique Baseline

Implementation completion: **100%**.

Completed:

- Restored the repository master-plan document and produced
  `docs/KQUANT_V2_GAP_ANALYSIS.md`.
- Audited application architecture, SQLite schema, API routes, stock signal
  engine, feature/label contracts, frontend composition, tests, and legacy
  quant modules.
- Recorded the dependency order, reuse plan, migration risks, and file-level
  Phase 1-5 plan.
- Confirmed the active boundary is read-only market data and research. Existing
  option code is a read-only prototype, not the v2 Options Engine.

Gate: **GO for audit; NO_GO for model or live use**.

### Week 2: Explicit Schema Migration

Implementation completion: **100%**.

Completed:

- Added the migration registry, ordered versions, checksums, transactional
  execution, and migration audit records under `kquant/db`.
- Kept legacy tables compatible rather than deleting or renaming them.
- Added schema fingerprint and backup/recovery checks.
- Registered isolated broker/MSTR legacy tables as quarantined from the active
  runtime.
- Added CLI and health visibility for schema state.

Gate: **GO for migration safety**. Empty databases, existing databases, repeat
migrations, and restore verification are covered by tests.

### Week 3: Data Snapshot And PIT Contract

Implementation completion: **100%**.

Completed:

- Added content-addressed snapshots with source, `as_of`, `available_at`,
  `fetched_at`, and content hash fields.
- Added source-status and forming-bar boundaries across Longbridge and legacy
  reference data.
- Added date-aware universe membership and an explicit
  `survivorship_limited` state where historical membership cannot be proven.
- Prevented Yahoo reference data and forming candles from entering eligible
  model data.

Gate: **GO for PIT contract**. Future-data perturbation and deterministic hash
tests pass.

### Week 4: Data Coverage And Quality Workbench

Implementation completion: **100% for the runtime and reporting contract**.

Completed:

- Added a versioned Universe Registry and aligned the active database universe
  to it.
- Added interval coverage, gaps, adjustment mode, provider state, company
  action status, market breadth status, and backfill quota reporting.
- Added controlled backfill queue/retry/audit behavior and quota recovery
  visibility.
- Added the Data Trust API and frontend evidence panel.

Gate: **GO for current runtime coverage**. Historical modeling remains
**NO-GO** because provider quota and historical coverage are not complete.

### Week 5: Theme Taxonomy v1

Implementation completion: **100%**.

Materialized result:

- Taxonomy version: `theme_taxonomy_v1.0.1`
- Taxonomy run: `ttr_e73e20778fd20572bf3c`
- Registry: `usr_eb0a628fbc333f57ea6c`
- Definitions: 25
- Mapped symbols: 294/296, 99.32%
- Membership records: 749 auto-mapped, 2 needs-review
- Point-in-time contract: true

The two unmapped symbols remain visible for review; they are not silently
forced into a theme. The taxonomy is classification infrastructure, not an
alpha or return claim.

Gate: **GO for taxonomy**; overall research Gate remains **NO_GO**.

### Week 6: Capital Rotation v0.1

Implementation completion: **100%**.

Fresh materialized result:

- Rotation version: `capital_rotation_v0.1.0`
- Rotation run: `crr_3ef3d56258c7b1960e5c`
- Taxonomy run: `ttr_e73e20778fd20572bf3c`
- As-of: `2026-08-22T04:52:33.421762+00:00`
- Source: `longbridge_candles`
- Ranked themes: 17
- Minimum theme members: 5
- Maximum single-member contribution: 10%, below the 15% cap
- Stress direction flips: 5; unreasonable flips: 0
- Future data used: false

The ranking is a same-timestamp deterministic research baseline. It is not a
forecast probability or OOS portfolio result.

Gate: **GO for deterministic rotation baseline**; predictive Gate remains
**NO-GO**.

### Week 7: Model And Dataset Infrastructure

Implementation completion: **100% for infrastructure**.

Completed:

- Added versioned Dataset Builder, Feature/Label Schema, date splits, rolling
  folds, purge and holding-period embargo.
- Added immutable dataset and sealed-test hashes.
- Added Model Artifact Registry with feature order, random seed, environment,
  dataset hash, and test partition hash.
- Added naive, rules/CRS and Logistic baseline adapters.
- Added fail-closed behavior on tampered or mismatched artifacts.

No production performance claim was generated from synthetic fixtures.

Gate: **GO for infrastructure; NO-GO for strategy deployment**.

### Week 8: Theme Prediction v1

Implementation completion: **100% for contracts and validation plumbing**.

Completed:

- Added direction, excess-return, ranking and quantile label contracts.
- Added Logistic baseline and optional LightGBM adapters without making the
  runtime depend on LightGBM.
- Added calibration and reliability diagnostics, including AUC, Brier, ECE,
  Rank IC, top-decile excess and bootstrap intervals.
- Added a three-fold calibration requirement and fail-closed probability
  display.

No qualifying materialized OOS Theme Prediction run currently exists. The UI
  must therefore show rules/limited evidence, not a probability.

Gate: **GO for infrastructure; NO-GO for probability display and trading use**.

### Week 9: Leadership Engine

Implementation completion: **100% for the descriptive engine and lineage
hardening**.

Fresh materialized result:

- Leadership run: `ldr_2e39a4a1d5d3228b0cc5`
- Rotation run: `crr_3ef3d56258c7b1960e5c`
- Taxonomy run: `ttr_e73e20778fd20572bf3c`
- Unique symbols: 293
- Future data used: false
- State counts: Leader 117, Emerging 92, Neutral 80, Weakening 203

The newest implementation also rejects an old Leadership run when its Rotation
or Taxonomy lineage is no longer current. The state counts are descriptive
cross-sectional output, not win rate or portfolio performance.

Gate: **GO for implementation; NO-GO for OOS leadership performance**.

### Week 10: Stock Quant Dataset And Model 0

Implementation completion: **100% for the kernel and interfaces**.

Completed:

- Frozen the read-only Stock Quant Model 0 feature and label contract.
- Unified the point-in-time feature snapshot used by live analysis and
  historical reconstruction.
- Added forward return, max run-up, max drawdown, realized R, and target/stop
  label handling with next-tradable-bar entry and stop-first conflict rules.
- Added Stock Quant ranking/detail APIs and evidence status.
- Added current Registry lineage checks. Old datasets now return
  `stale_registry`, produce no ranking, and cannot be interpreted as current.

The existing historical validation artifacts were created against an older
Registry and are intentionally blocked until a new aligned dataset is sealed.

Gate: **GO for implementation; NO-GO for research deployment until resealed**.

### Week 11: Stock Quant Models And OOS Validation

Implementation completion: **100% for multi-fold validation and release gates**.

The latest available historical diagnostic, before current Registry invalidation,
was:

| Model | Final selected test trades | Final average R | Final PF | Final max DD | Aggregate 3-fold avg R | Aggregate 3-fold PF | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Model 0 rule | 144 | +0.10065R | 1.33179 | 11.29433R | +0.07010R | 1.22294 | NO-GO |
| Logistic | 25 | +0.35139R | 3.34870 | 1.39238R | -0.02036R | 0.93925 | NO-GO |

These values are historical diagnostics only and are not current deployable
metrics because their dataset lineage is stale. Model 0 also had a negative
bootstrap lower bound for average R; drawdown exceeded the 8R limit; the
Logistic result was unstable across folds and had too few final test trades.

The current read APIs now expose `stale_registry` and fail closed rather than
serving these numbers as current performance.

Gate: **NO-GO**. A fresh aligned dataset and a new immutable validation run are
required after the Longbridge backfill quota recovers.

### Week 12: Product Integration, Shadow Run And Release Audit

Implementation completion: **100% for the read-only product surface**.

Completed:

- Connected Capital Rotation, Theme, Leadership, Stock Quant, Data Trust and
  Shadow status into the Today/readiness workbench.
- Added version, evidence, lineage, failure reason, and downgrade-state
  visibility.
- Extracted major Quant, Operations, Early Trend, Research, Settings, and
  Chart panels from the frontend monolith while preserving contracts.
- Added PWA/static version checks, mobile layout, Service Worker boundaries,
  backup/recovery checks, and read-only route scans.
- Added release hardening so no deployable model or Shadow session can start
  on a stale or incomplete validation artifact.

The 20 real-trading-day Shadow Observation window has not completed. Code and
historical tests cannot substitute for forward observations.

Gate: **GO for code release surface; NO-GO for Shadow and trading use**.

## 4. Current Performance Evidence

The system must not currently report a live win rate or live Profit Factor.
The only available performance-like numbers are the stale historical Model 0
and Logistic diagnostics listed in Week 11, and they are blocked from current
reads. The following are explicitly unavailable:

- current aligned test-set strategy result;
- current multi-fold OOS result from the active Registry;
- 20 real trading days of Shadow Observation;
- 30 forward actionable outcomes;
- Paper/Shadow completed trade evidence;
- event-day stratification with an ingested event calendar;
- complete 296-symbol historical Longbridge dataset.

The previous historical-label summaries remain legacy descriptive evidence. They
must not be called strategy win rate, real-money win rate, or model accuracy.

## 5. Safety And Boundary Review

The active runtime remains deliberately read-only:

- no broker/account/position/order route;
- no order submission or automatic execution;
- no options order route; options remain read-only research only;
- Longbridge is market data and calendar only;
- Yahoo is reference/audit data only;
- model or stale-data failures fail closed;
- a Registry change invalidates downstream artifacts rather than rewriting
  history.

The current read-only boundary scan reports 101 registered routes with no
forbidden account, position, broker, or order-submission route.

## 6. Verification Results

Latest verification after the lineage hardening:

- Python: `237 passed` in `337.35s`.
- Focused lineage and domain regression: `38 passed` in `19.71s`.
- Frontend tests: `2 passed`.
- React/Vite production build: passed; existing single JavaScript chunk remains
  above the 500 kB warning threshold.
- Read-only boundary scan: passed; 101 routes, no forbidden trade routes.
- `git diff --check`: passed.
- Browser desktop smoke: title, Longbridge status, research rail, current stock
  workbench and no error overlay verified.
- Browser mobile smoke at 375x812: no horizontal overflow, Longbridge status and
  research rail present, no error overlay.
- Browser console: zero errors during the smoke run.

## 7. Technical Debt And Next Blockers

1. Historical Longbridge quota recovery is the primary external blocker. On or
   after 2026-09-01, run the controlled backfill and record the provider result.
2. Rebuild the current aligned Stock Quant dataset from the current Registry;
   do not revive the old dataset by changing its Registry ID.
3. Re-run the immutable multi-fold validation using the newly sealed dataset.
4. Ingest and version the corporate event calendar before using event-aware
   model results.
5. Complete breadth coverage before interpreting market breadth as full-universe
   evidence.
6. Run at least 20 real trading days of Shadow Observation and at least 30
   traceable forward outcomes.
7. Continue frontend decomposition and reduce the production bundle warning,
   but do not let UI work outrun data and OOS gates.

## 8. Final Go / No-Go

**Final implementation status:** the planned read-only v2 architecture and
research plumbing are substantially implemented through Week 12.

**Final research status:** `NO_GO`.

Reasons:

- active Stock Quant validation is stale after Registry repair;
- historical coverage is only 33.45% for the canonical validation window;
- event calendar is not ingested;
- available OOS diagnostics fail one or more sample, confidence, PF, stability,
  or drawdown gates;
- no forward Shadow Observation window has completed.

No amount of UI readiness changes these conclusions. The correct next action is
data recovery, current-dataset resealing, and re-validation, not parameter
tuning or live integration.

## 9. Commits And Rollback Points

Relevant branch history:

- `884bc57` data boundary and Registry stability
- `f3e3dfb` Theme Taxonomy audit
- `528e16d` stale Rotation/Taxonomy lineage guard
- `f08717d` Theme Taxonomy and Capital Rotation gate reports
- `2152389` stale downstream research lineage guard for Leadership and Stock
  Quant

The latest working tree is clean on `codex/kquant-v2-gap-analysis`. Each report
and implementation slice remains separately reviewable and reversible. No
remote push was performed as part of this reconciliation.

## 10. Next Weekly Work Package

The next week should be a repair/revalidation week rather than a new model week:

1. Recheck Longbridge quota and execute the controlled historical backfill.
2. Seal a new current-Registry Stock Quant dataset with immutable hashes.
3. Run the full validation matrix again without inspecting the test partition
   for parameter choice.
4. Update the readiness and Today evidence only from the new aligned run.
5. If the data gate remains below 90%, keep all predictive and Shadow gates
   `NO_GO` and report the exact missing symbols and provider reason.

Until those steps pass, KQUANT remains a read-only research terminal and does
not become a live trading system.
