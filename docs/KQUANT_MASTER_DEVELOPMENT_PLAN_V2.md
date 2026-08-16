# KQUANT v2 Master Development Plan

Status: approved execution baseline
Recorded: 2026-08-16
Source: user-confirmed twelve-week KQUANT v2 development plan

This repository copy is the authoritative execution baseline for the current
KQUANT v2 programme. It records the plan explicitly confirmed for implementation
after the original temporary attachment was no longer available. It does not
claim to be a byte-for-byte recovery of that expired attachment.

## Programme Summary

KQUANT v2 progresses in this dependency order:

`Architecture Audit -> Data Trust -> Capital Rotation -> Theme Prediction -> Leadership -> Stock Quant`

The programme does not build a new Options Engine, automated execution, broker
account access, positions, or order submission. Existing options capabilities
remain a read-only research prototype until Stock Quant clears its OOS gates.

Each week has a reviewable commit, a weekly report, a test/build run, a leakage
review, and a Go/No-Go decision. A failed gate is repaired before dependent
work proceeds. Calendar-time evidence cannot be accelerated or represented by
synthetic elapsed time. The runtime remains a read-only research system.

## Week 1: Architecture Audit and Single Baseline

- Audit architecture, data flow, schema, APIs, Feature and Label contracts,
  strategy versioning, quant/backtest modules, frontend, and tests.
- Record table counts, data time ranges, indexes, universe discrepancies, and
  Longbridge coverage.
- Create a version matrix for application, schema, dataset, feature, label,
  strategy, model, and frontend.
- Produce the v2 gap analysis, Phase 1-5 file plan, risk register, leakage
  analysis, test strategy, and Go/No-Go gates.

Gate: baseline tests/build pass, facts are reproducible, and no runtime or DB
data modification is included.

## Week 2: Explicit Schema Migration

- Add `kquant/db` with ordered migrations, checksums, transactions, and audit.
- Replace schema-on-connect with a compatible explicit migration entry point.
- Add schema fingerprint, backup preflight, restore verification, health and CLI.
- Quarantine orphan broker/MSTR-era tables; active runtime must not read them.

Gate: empty/current/repeated migrations and verified restore reproduce schema and
row hashes.

## Week 3: Data Snapshot and Point-in-Time Contract

- Add Data Snapshot and item records with source, `as_of`, `available_at`,
  `fetched_at`, and content hash.
- Normalize Longbridge, Yahoo reference, corporate-action, and calendar states.
- Exclude forming bars from strategy, label, and model snapshots.
- Support membership-by-date and label incomplete history `survivorship_limited`.
- Preserve Yahoo for audit only; it cannot be an eligible model input.

Gate: snapshot hashes reproduce and future-data changes cannot modify historical
snapshots.

## Week 4: Data Coverage and Quality Workbench

- Unify code and database universes under one versioned registry.
- Surface coverage, gaps, adjustment mode, corporate actions, and update time.
- Build controlled Longbridge backfill with limits, retry, resume, and audit.
- Add Data Trust UI plus `/api/data/coverage` and `/api/data/snapshots/{id}`.
- Add provider-event retention/archival policy.

Gate: Longbridge 1D and 1H coverage reach 90% of the modeling universe; below
that threshold only coverage repair may proceed.

## Week 5: Theme Taxonomy v1

- Add versioned Theme Definitions, hierarchy, aliases, status, and effective dates.
- Split flat tags into themes, industries, risk/style, liquidity, and instruments.
- Add Membership weights, evidence, confidence, review status, and dates.
- Add `config/theme_taxonomy_v1.yml` and taxonomy audit UI.

Gate: 95% of eligible symbols are mapped or explicitly unmapped; all memberships
have effective dates.

## Week 6: Capital Rotation V0.1

- Build PIT theme returns, relative strength, acceleration, breadth, turnover,
  volume, persistence, and transparent flow proxies.
- Implement deterministic Capital Rotation Score as the pre-model baseline.
- Require five eligible constituents and cap one constituent's contribution.
- Add ranking, detail, constituent, data-quality, and history APIs/UI.

Gate: PIT replays are deterministic and leave-largest-member-out checks remain
directionally stable.

## Week 7: Model and Dataset Infrastructure

- Add Dataset Builder, Feature/Label Schema Version, and Model Artifact Registry.
- Split by trading date with rolling folds, purge, and holding-period embargo.
- Persist configuration, snapshot, feature order, seed, artifact hash, and environment.
- Establish naive, deterministic CRS, and Logistic baselines.
- Seal test partitions from parameter selection and calibration.

Gate: versioned runs reproduce exactly; artifact/data mismatch fails closed.

## Week 8: Theme Prediction v1

- Add theme direction, excess-return, ranking, and quantile labels.
- Compare Logistic with LightGBM classification, regression, and quantile models.
- Compare Platt and Isotonic calibration on validation data only.
- Report AUC, Brier, ECE, Rank IC, top-decile excess, stability, and confidence.
- Show probability only after calibration passes.

Gate: three OOS folds; AUC lower bound above 0.5; Brier beats climatology;
positive Rank IC; recommended ECE <= 0.05.

## Week 9: Leadership Engine

- Rank stocks within immutable Theme Snapshots using relative-theme and
  relative-market performance, volume, breadth, and persistence.
- Categorize Leader, Emerging, Neutral, and Weakening with evidence.
- Add leader APIs and frontend panels with concentration validation.

Gate: OOS leader basket beats theme equal weight after conservative costs and
retains positive Rank IC across folds/regimes.

## Week 10: Stock Quant Dataset and Shared Strategy Core

- Freeze existing rules as Model 0.
- Use one pure real-time and replay feature/strategy core.
- Add trend, relative strength, theme, leadership, volume/price, risk, and event features.
- Define forward return, max run-up/drawdown, realized R, and target/stop labels.
- Use next-tradable-bar entry, actual gaps, and stop-first conflicts.
- Retain `historical_edge` as legacy descriptive evidence only.

Gate: real-time/replay features agree and future candles cannot change history.

## Week 11: Stock Quant Models and OOS Validation

- Compare Model 0, Logistic, LightGBM, and Quantile approaches.
- Report calibrated probability, expected return, downside risk, range, and evidence.
- Run costs, industry, regime, sensitivity, and concentration tests.
- Keep ranking separate from execution eligibility and hard safety gates.

Gate: 100 completed sealed-test trades; bootstrap mean-R lower bound above zero;
Profit Factor >= 1.25; maximum drawdown <= 8%.

## Week 12: Product Integration, Shadow Run, and Release Audit

- Integrate Market Regime, Capital Rotation, Theme, Leadership, and Stock Quant.
- Display trust, model version, snapshot, evidence, invalidation, and degradation.
- Split frontend by feature and complete performance/security/PWA/mobile/restore checks.
- Start a 20-trading-day Shadow Observation; code completion is not live authorization.

Final gate: removing best five symbols leaves positive expected value; no symbol
supplies more than 15% of profit; conservative-cost PF >= 1.05; retain `NO_GO`
until forward observation completes.

## Weekly Report Contract

Every weekly report states the objective/completion percentage, changed runtime
modules/schema/APIs/UI, coverage and quality movement, verification results,
new technical debt and leakage risks, train/validation/sealed-test/forward
results separated, Go/No-Go, commit and rollback point, and next-week blockers.

Baseline verification: Python tests, frontend tests, production build, read-only
route scan, and `git diff --check`. Future v2 endpoints cover data snapshots,
themes, leadership, models, and quant research; they must never add broker,
account, position, or order-submission interfaces.
