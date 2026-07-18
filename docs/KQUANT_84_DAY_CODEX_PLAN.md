# KQUANT 84-Day Codex Execution Plan

Status: canonical execution specification

Baseline date: 2026-07-18

Formal project day: Day 1
Source: `KQUANT 84 天持续开发计划.pdf`

## 1. Product Goal

KQUANT is a read-only US equity research system for one human trader. The
84-day program is complete only when the system has trustworthy point-in-time
data, a reproducible long-only strategy, realistic out-of-sample evidence,
clear entry/stop/target/position plans, and a complete forward-observation
journal.

The program does not promise a fixed win rate. Its optimization target is
positive, reproducible expectancy after conservative costs, with controlled
drawdown and explicit uncertainty.

## 2. Frozen Scope

- Market: US-listed stocks and ETFs.
- Direction: long-only.
- Active validation strategy: `swing_long_v1` only.
- Intended holding period: approximately one week to two months.
- Signal timeframes: daily trend plus 1-hour confirmation.
- Universe: curated Core 100/200 with point-in-time membership rules.
- Primary market data: Longbridge read-only quote and candle APIs.
- Reference data: Yahoo, clearly labeled and never sufficient for a real-money
  BUY decision.
- Execution: manual only.
- AI role: explain, rank, summarize, and propose a plan from deterministic
  features. AI cannot bypass hard rules or submit an order.

The following code may remain in the repository but is frozen and receives no
new scope during this plan: options, crypto, MSTR feature expansion, additional
strategy profiles, additional agents, broker/account/position access,
automatic execution, social/community features, native applications, and
unrelated large UI redesigns.

## 3. Daily Engineering Rules

1. One primary objective per day.
2. One rollbackable commit per day.
3. Every strategy change receives an immutable version and configuration hash.
4. No future information may enter a feature, universe, signal, or fill.
5. AI output never overrides stale data, provider failure, missing stops, or
   any other hard veto.
6. Run the Python suite and frontend production build before committing.
7. Scan tracked and untracked source files for credentials before committing.
8. Record evidence, risks, decisions, and the next objective in
   `docs/daily/YYYY-MM-DD.md`.
9. Do not delete tests merely to make a build pass; replace obsolete coverage
   with equivalent current-path coverage.
10. Generated databases, caches, reports containing local state, and secrets
    stay out of Git.

## 4. Definition of Done

The project is not production-ready because the UI looks complete. It becomes
eligible for a small-money manual pilot only after all data, engineering,
strategy, and forward-observation gates in Section 7 pass.

## 5. Day-by-Day Roadmap

### Week 1: Rebaseline and Freeze

| Day | Objective | Required deliverable |
|---:|---|---|
| 1 | Audit the current system | `docs/current_system_audit.md`, canonical plan, daily log, green baseline tests |
| 2 | Define the personal live MVP | `docs/personal_live_mvp.md` with user flow, No Trade conditions, and acceptance criteria |
| 3 | Freeze the strategy specification | `docs/strategy_specification.md`; only `swing_long_v1` remains active for validation |
| 4 | Define the market-data contract | `docs/market_data_contract.md` covering UTC, exchange time, adjustment, completed bars, and freshness |
| 5 | Add immutable strategy versioning | Version/config snapshot/hash schema; all signals and tests bind to a version |
| 6 | Create one validation entry point | Local validation command plus GitHub CI for tests, build, secret scan, and runtime checks |
| 7 | Review Week 1 | Completion matrix, unresolved risks, and explicit Week 2 go/no-go |

### Week 2: Trustworthy Longbridge Data Foundation

| Day | Objective | Required deliverable |
|---:|---|---|
| 8 | Audit Longbridge capabilities and permissions | `docs/longbridge_provider_audit.md` with entitlement and failure evidence |
| 9 | Normalize candle storage | Idempotent upsert, source lineage, raw/adjusted status, and uniqueness tests |
| 10 | Implement the market clock | DST, holidays, early closes, sessions, forming/closed bars, and freshness tests |
| 11 | Handle splits and dividends | Adjustment policy, corporate-action tests, and historical consistency checks |
| 12 | Build a point-in-time universe | Membership effective dates and delisted/survivorship-safe reconstruction |
| 13 | Add data-quality gates | Missing, duplicate, outlier, stale, timezone, and source-divergence reports |
| 14 | Run provider fault injection | Timeout, rate limit, stale cache, partial response, and provider switch tests |

### Week 3: Rebuild and Lock `swing_long_v1`

| Day | Objective | Required deliverable |
|---:|---|---|
| 15 | Define the feature interface | Point-in-time feature packet schema and provenance |
| 16 | Implement daily trend features | Deterministic EMA/trend/relative-strength tests |
| 17 | Implement 1-hour confirmation | Momentum, volume, VWAP, and completed-bar confirmation tests |
| 18 | Implement risk features | ATR, gap, extension, liquidity, and event-risk inputs |
| 19 | Freeze the score | Versioned score formula and boundary tests |
| 20 | Freeze hard vetoes | Stale/provider/risk/liquidity/plan veto matrix |
| 21 | Create 20 golden cases | Hand-audited BUY/WATCH/PASS/NO_TRADE fixtures with expected reasons |

### Week 4: Reproducible Historical Validation

| Day | Objective | Required deliverable |
|---:|---|---|
| 22 | Reconstruct historical signals | As-of signal generation without current-state leakage |
| 23 | Implement fill semantics | Next-bar entry, gap handling, stop-first conflict rule, and no look-ahead tests |
| 24 | Add transaction costs | Commission, spread, slippage, and stressed-cost scenarios |
| 25 | Build portfolio simulation | Position overlap, exposure limits, and cash accounting |
| 26 | Define benchmarks | SPY, QQQ, and simple trend baselines |
| 27 | Produce complete metrics | Win rate, average R, expectancy, PF, drawdown, turnover, and confidence intervals |
| 28 | Prove reproducibility | Same snapshot/config/seed produces identical results |

### Week 5: Out-of-Sample Strategy Evidence

| Day | Objective | Required deliverable |
|---:|---|---|
| 29 | Run rolling walk-forward | Train/validation/test windows with untouched holdout data |
| 30 | Run parameter sensitivity | Stability surfaces instead of single best parameters |
| 31 | Segment market regimes | Risk-on, caution, risk-off, volatility, and trend regimes |
| 32 | Test concentration | Symbol, sector, theme, and time concentration diagnostics |
| 33 | Quantify uncertainty | Confidence intervals and deflated performance statistics |
| 34 | Create the Evidence Score | Transparent evidence grade combining sample, stability, and OOS quality |
| 35 | Freeze `swing_long_v1.0.0` | Immutable configuration, hash, evidence pack, and release note |

### Week 6: Daily Decision and Journal Loop

| Day | Objective | Required deliverable |
|---:|---|---|
| 36 | Generate a daily shortlist | Deterministic ranked candidates with data-quality reasons |
| 37 | Generate trade plans | Entry, stop, target, invalidation, no-chase, and R:R |
| 38 | Add position sizing | Equity-risk sizing with caps and gap-aware risk |
| 39 | Add a decision ledger | Every plan, veto, AI response, and user decision is append-only |
| 40 | Complete the journal | Reviewed/skipped/entered/exited records and required fields |
| 41 | Add attribution | Rule, feature, data, execution, and behavior attribution |
| 42 | Generate a weekly report | Plan adherence, expectancy, errors, and next-week actions |

### Week 7: Production Engineering Foundation

| Day | Objective | Required deliverable |
|---:|---|---|
| 43 | Define production architecture | Hosted API, worker, database, cache, and frontend boundaries |
| 44 | Plan SQLite-to-Postgres migration | Schema compatibility, migration, rollback, and verification |
| 45 | Add a scheduler | Idempotent ingestion, scan, report, and retry jobs |
| 46 | Add notification boundaries | Research-only alerts with deduplication and quiet periods |
| 47 | Add monitoring | Provider, latency, staleness, failures, and data-quality dashboards |
| 48 | Test backup and recovery | Restore drill with documented RTO/RPO |
| 49 | Complete security review | Secrets, auth, least privilege, audit, and no-order proof |

### Week 8: Production UI Release Candidate

| Day | Objective | Required deliverable |
|---:|---|---|
| 50 | Finalize Today workspace | Shortlist, data trust, and current readiness at a glance |
| 51 | Finalize stock decision page | One answer, evidence, plan, and guardrails |
| 52 | Build Risk Center | Exposure, daily risk, stale data, and No Trade reasons |
| 53 | Finalize Journal/Review UI | Fast entry, exit, and attribution workflow |
| 54 | Complete mobile/PWA behavior | Tablet/mobile navigation and offline-safe states |
| 55 | Complete abnormal-state UX | Provider, AI, cache, database, and partial-data failures |
| 56 | Cut RC1 | Versioned build, test evidence, known issues, and rollback |

### Weeks 9-10: Forward Observation, Part 1

| Day | Objective | Required deliverable |
|---:|---|---|
| 57 | Prepare forward observation | Frozen strategy/data contracts and observation protocol |
| 58 | Observe trading day 1 | Complete signal/decision/outcome log |
| 59 | Observe trading day 2 | Complete signal/decision/outcome log |
| 60 | Observe trading day 3 | Complete signal/decision/outcome log |
| 61 | Observe trading day 4 | Complete signal/decision/outcome log |
| 62 | Observe trading day 5 | Complete signal/decision/outcome log |
| 63 | Review forward week 1 | Data, signal, behavior, and incident report |
| 64 | Prepare simulation account rules | Fixed simulated equity, costs, and execution rules |
| 65 | Simulate trading day 1 | Complete simulated execution log |
| 66 | Simulate trading day 2 | Complete simulated execution log |
| 67 | Simulate trading day 3 | Complete simulated execution log |
| 68 | Simulate trading day 4 | Complete simulated execution log |
| 69 | Simulate trading day 5 | Complete simulated execution log |
| 70 | Review forward week 2 | Expectancy, adherence, incidents, and evidence delta |

### Week 11: Forward Observation, Part 2 and Decision Gate

| Day | Objective | Required deliverable |
|---:|---|---|
| 71 | Simulate trading day 6 | Complete simulated execution log |
| 72 | Simulate trading day 7 | Complete simulated execution log |
| 73 | Simulate trading day 8 | Complete simulated execution log |
| 74 | Simulate trading day 9 | Complete simulated execution log |
| 75 | Simulate trading day 10 | Complete simulated execution log |
| 76 | Produce validation report | Historical plus at least 15 forward days, incidents, and uncertainty |
| 77 | Run Go/No-Go review | Signed checklist; no pilot if any mandatory gate fails |

### Week 12: Controlled Small-Money Manual Pilot

| Day | Objective | Required deliverable |
|---:|---|---|
| 78 | Prepare pilot | Rotate secrets, freeze release, confirm limits, rehearse rollback |
| 79 | Small-money day 1 | At most one manual trade, complete pre/post journal |
| 80 | Small-money day 2 | At most one manual trade, complete pre/post journal |
| 81 | Small-money day 3 | At most one manual trade, complete pre/post journal |
| 82 | Small-money day 4 | At most one manual trade, complete pre/post journal |
| 83 | Small-money day 5 | At most one manual trade, complete pre/post journal |
| 84 | Production review | Continue, pause, or stop decision with complete evidence pack |

## 6. Current Baseline Mapping

As of 2026-07-18, KQUANT contains functional work that resembles later-day
deliverables, including a React workbench, Longbridge integration, AI plans,
historical label tables, and journal APIs. These do not count as completed plan
days until their prerequisites and evidence gates pass.

The formal position is Day 1 because the repository did not yet contain the
canonical scope, current-system audit, frozen strategy specification, market
data contract, immutable strategy version, reproducible point-in-time
validation, action outcomes, or completed forward-observation journal.

## 7. Mandatory Gates

### Data gate

- Every value has source and event time.
- No future information or current-universe leakage.
- No mixing of previous-day and current-day state without a visible label.
- Stale or failed primary data blocks every buy-class action.
- Fixture data never appears in the user-facing live path.
- Corporate actions, completed bars, timezone, and adjustment semantics are
  tested.

### Engineering gate

- Python tests, frontend build, and critical browser flow pass.
- Database backup/restore and rollback are proven.
- Monitoring and provider-failure alerts work.
- No credential is tracked, logged, or shipped to the frontend.
- Active runtime has no account, position, broker context, or order-submit path.

### Strategy gate

- At least 100 completed historical trades for the frozen strategy.
- Out-of-sample average R is positive after conservative costs.
- Out-of-sample Profit Factor is greater than 1.
- Walk-forward testing does not fail broadly across periods.
- Results are not dominated by a few symbols, themes, or dates.
- Parameter neighborhoods are stable.
- Performance improves on documented simple benchmarks.
- Maximum drawdown is within the predeclared tolerance.

### Forward-observation gate

- At least 15 complete trading days under frozen rules.
- Every candidate, skip, entry, exit, error, and data incident is logged.
- No unresolved critical provider, timestamp, or signal-reconstruction issue.

### Small-money gate

- Day 77 Go decision recorded.
- Maximum risk per trade: 0.25% of account equity.
- Initial limit: at most one manual trade per day.
- No automated execution.
- Stop immediately on data-integrity failure or drawdown-limit breach.

## 8. Change Control

Any request that expands frozen scope must be recorded as backlog, not inserted
into the active day. A failed prerequisite moves the project back to the first
failed day. UI completeness never substitutes for data or strategy evidence.
