# KQUANT Current System Audit

Audit date: 2026-07-18

Formal roadmap position: Day 1 of 84

Repository: `Tommydiao/KQUANT-`

Branch: `main`

Pre-audit HEAD: `d2d65f7492857aa9c76380a5e3ab8179bb2f8b5b`

## 1. Executive Conclusion

KQUANT has a comparatively mature product shell, but it does not yet have a
strategy evidence chain suitable for claiming a validated win rate or for
formal real-money release.

The repository already contains search, charts, stock decision views, AI
plans, Deep Research, MSTR analysis, a journal workflow, Longbridge and Yahoo
providers, historical feature/label tables, and a substantial automated test
suite. Those are valuable assets. They are not substitutes for an immutable
strategy version, point-in-time reconstruction, walk-forward validation,
completed action outcomes, and forward-observation records.

Formal status is therefore **Day 1**, not a later UI or deployment phase.

## 2. Baseline Verification

| Check | Result | Assessment |
|---|---:|---|
| Python test suite | 209 passed, 1 warning | Healthy baseline |
| React production build | Passed | Healthy; Vite chunk-size warning remains |
| Current tracked plaintext credential scan | No matches | Pass for current worktree |
| Local stock database | Present, about 585 MB | Large evidence store, not yet a trusted validation snapshot |
| Active broker/account/order integration | None in `kquant` runtime | Pass |
| Formal strategy validation runs | 0 | Critical gap |
| Completed AI action outcomes | 0 | Critical gap |
| Stock signal journal records | 0 | Critical gap |

The current uncommitted runtime changes improve secure Longbridge setup,
startup checks, realtime diagnostics, and runtime tests. They do not alter BUY
thresholds or trading logic. They are included in the Day 1 rollback baseline
after the checks in this document pass.

## 3. Architecture Inventory

### Active product path

| Area | Location | Status | Evidence / note |
|---|---|---|---|
| Python application | `kquant/` | Partial | Stock data, signal, AI, validation, and HTTP services exist |
| React frontend | `web/src/` | Partial | Workbench, search, stock decision, charts, AI plan, research, journal, and MSTR views exist |
| Static delivery | Python dashboard server plus `web/dist` | Partial | Works locally; production hosting boundary is not frozen |
| Database | `work/kquant_us.sqlite3` | Partial | Substantial data exists; point-in-time and immutable version guarantees are incomplete |
| Runtime scripts | root PowerShell/CMD scripts | Partial | Startup, Longbridge setup, realtime check, and preflight exist |
| Tests | `tests/` | Partial | Broad regression coverage; formal no-look-ahead and production E2E gates remain incomplete |
| Documentation | `docs/` | Partial | Local/pilot docs exist; canonical 84-day evidence docs began on Day 1 |

### Legacy and frozen code

| Area | Status | Decision |
|---|---|---|
| `btc_eth_15m/` legacy package | Inactive legacy path | Freeze; it must not define the active KQUANT product or safety claim |
| Options functionality and tests | Existing secondary code | Freeze until the stock strategy passes its evidence gates |
| MSTR Cycle Radar | Existing advanced feature | Keep available but freeze new work |
| Extra strategy profiles | Implemented and exposed | Freeze for validation; only `swing_long_v1` is active in the 84-day program |
| Additional AI agents / Deep Research | Existing | Keep read-only; do not expand before prerequisites pass |

Legacy files contain historical paper/testnet/order-oriented concepts. They are
not wired into the active `kquant` runtime, but their presence is a scope and
safety-maintenance risk. Isolation or archival should be planned after the
Week 1 freeze, not silently treated as completed safety work.

## 4. Public Interface Inventory

The backend currently exposes several interface groups:

- Runtime and safety health.
- Stock universe, search, candles, quote, realtime snapshot, provider health,
  signals, and single-stock analysis.
- AI status, structured stock decisions, Daily Agent reports, Deep Research,
  and action validation.
- Journal and readiness/Pilot records.
- MSTR cycle analysis.
- Legacy/secondary options interfaces.

The interface surface is broader than the frozen MVP. During Days 2-3, the
active interface must be identified explicitly and all other routes classified
as frozen, internal, or legacy. An endpoint existing is not evidence that its
data contract or strategy behavior is production-ready.

## 5. Database Audit

Database inspected: `work/kquant_us.sqlite3`.

| Table | Rows | Assessment |
|---|---:|---|
| `stock_universe` | 264 | Universe exists; point-in-time membership is not proven |
| `stock_candles` | 251,327 | Good volume; mixed source/fixture history requires lineage controls |
| `stock_signal_runs` | 386 | Runs exist; immutable strategy version binding is incomplete |
| `stock_signals` | 39,357 | Useful raw material, not a validated result set |
| `stock_features` | 39,210 | Features exist; as-of reconstruction contract is not frozen |
| `stock_labels` | 2,126,963 | Labels exist; no-look-ahead and fill semantics need formal tests |
| `stock_backtest_runs` | 381 | Historical runs exist; not equivalent to approved validation runs |
| `strategy_validation_runs` | 0 | Formal strategy validation not started |
| `ai_action_events` | 4 | Insufficient action history |
| `ai_action_outcomes` | 0 | No outcome evidence |
| `stock_signal_journal` | 0 | No forward/manual decision evidence |
| `provider_events` | 93,802 | Strong diagnostic volume; needs summarized reliability SLOs |
| `audit_events` | 398 | Audit trail exists but is not yet the canonical decision ledger |

### Database contract gaps

- No immutable strategy-version/configuration-hash relation is proven across
  signals, features, labels, AI actions, and backtests.
- `stock_candles` records source and provider status, but raw/adjusted policy,
  corporate-action version, bar completion, and ingestion snapshot are not all
  frozen in one contract.
- Existing fixture rows must remain excluded from all live and validation
  datasets by enforceable queries and tests.
- Universe membership does not yet provide a complete effective-date history.
- Existing reports are generated artifacts, not an immutable evidence pack.

## 6. Market Data and Provider Audit

### Observed provider history

| Provider | Available events | Unavailable events | Latest observed data | Assessment |
|---|---:|---:|---|---|
| Longbridge | 313 | 637 | 2026-07-09 | Primary source is integrated but reliability is not yet acceptable |
| Yahoo/public | 78,160 | 11,582 | 2026-07-14 | Broad historical/reference coverage; not approved for real-money BUY |

The Longbridge implementation includes a persistent quote context, normalized
candles, realtime snapshots, forming-bar concepts, and local health checks.
However, successful event count is below failure count in the inspected
history, and recent Longbridge evidence is stale relative to the audit date.
This is **partial completion**, not a trusted realtime engine.

### Data risks

- Longbridge credentials and quote entitlement may be present while individual
  requests still fail; configuration presence is not provider health.
- The UI has previously shown source/time states that users interpreted as
  realtime even when the latest candle was old.
- Longbridge and Yahoo histories coexist; every downstream decision must carry
  source lineage and enforce primary-source requirements.
- Market time, China time, New York time, daylight saving time, holidays,
  early close, and forming versus closed bars need one tested contract.
- Yahoo fallback may be displayed for reference, but it must hard-veto every
  buy-class action.
- Fixture rows remain in the local database and must never enter a live result
  or validation sample.

### Credential incident

Longbridge credentials appeared in prior screenshots. Treat them as exposed.
The old token must be revoked in the Longbridge console and replaced. This is
an external action and cannot be certified by repository tests. New credentials
must be stored only in a local ignored `.env` or operating-system secret store.

## 7. Strategy and AI Audit

### Implemented profiles

- `swing_long_v1`
- `tactical_1w_v1`
- `position_6m_v1`
- `cycle_1_3y_v1`
- `high_beta_growth_v1`

Additional AI actions, including probe/pullback/watch variants, are also
implemented. This demonstrates product experimentation, not validated edge.

### Active validation decision

For the 84-day program, only `swing_long_v1` is active. All other profiles and
MSTR/option-specific logic are frozen. They may remain visible in development,
but their results do not count toward strategy approval.

### Existing strengths

- Deterministic indicators and hard-veto concepts exist.
- AI Feature Packets contain structured market evidence.
- AI outputs structured entry, stop, target, R:R, invalidation, and position
  hints.
- Provider failure and stale data are intended to block buy-class actions.
- Historical feature and label infrastructure provides a useful starting point.

### Critical strategy gaps

- No immutable `swing_long_v1` strategy version/config hash.
- No approved point-in-time universe reconstruction.
- No signed strategy specification for feature timing, entry, exit, and costs.
- No approved next-bar fill and same-bar stop/target conflict evidence pack.
- No formal walk-forward run in `strategy_validation_runs`.
- No untouched test-period result or benchmark comparison.
- No AI action outcomes and no forward-observation journal entries.
- Current sample/win-rate displays can be mistaken for validated edge even when
  the formal evidence table is empty.

Therefore KQUANT must not claim that its win rate, expected value, or AI action
quality has been proven.

## 8. Frontend and Product Audit

### Implemented

- Search and direct stock decision workflow.
- TradingView-style K-line charts and multiple timeframes.
- AI action/plan, guardrails, trade ticket, and risk explanations.
- Daily opportunity surface, watchlist, market layers, MSTR, research chat,
  journal, settings, Chinese/English, dark/light, and responsive structure.

### Partial or misleading states

- Product maturity can visually imply strategy maturity.
- Advanced/frozen profiles remain prominent even though only one strategy will
  be validated.
- Diagnostic and readiness data can become stale while appearing authoritative.
- Realtime labels must be bound to actual quote/bar age, not merely provider
  configuration.
- The removal of old static-dashboard assertions in
  `tests/test_options_lab.py` needs replacement with React-path browser or
  component coverage; obsolete tests should not simply disappear.

The UI is an asset to preserve. It is not the active bottleneck for Weeks 1-5.

## 9. Runtime, Scripts, and Deployment Audit

### Current local tooling

- One-click stock-terminal startup scripts.
- Longbridge credential setup scripts using secure prompts.
- Longbridge realtime self-check scripts.
- Monday/preflight checks.
- Local SQLite and React build workflow.

### Current deployment position

Local mode is the only research environment with the full backend and secret
context. Vercel/Cloudflare experiments are demonstration links, not an approved
production backend. The production architecture, hosted database, scheduler,
monitoring, backup, and recovery work belong to Week 7.

## 10. 84-Day Completion Matrix

| Phase | Functional assets already present | Formal completion | Reason |
|---|---|---|---|
| Week 1 baseline | Tests, docs fragments, local scripts | Day 1 in progress | Canonical scope/audit/log only now being created |
| Week 2 data foundation | Longbridge/Yahoo providers, DB, realtime concepts | Not complete | Reliability, PIT, adjustment, and fault-injection gates absent |
| Week 3 strategy lock | Indicators, profiles, hard vetoes | Not complete | No single frozen specification/version or golden-case pack |
| Weeks 4-5 validation | Features, labels, backtest scaffolding | Not complete | Formal validation table empty; no approved OOS evidence |
| Week 6 daily loop | AI Daily, plan, journal API/UI | Not complete | Journal and outcomes empty; no frozen strategy linkage |
| Week 7 production engineering | Local scripts, demo deployment work | Not complete | Hosted architecture, Postgres, scheduler, monitoring, restore absent |
| Week 8 production UI | Mature workbench assets | Partial, out of sequence | Must be verified against frozen contracts and abnormal states |
| Weeks 9-11 forward observation | Report shapes exist | Not started | No 15-day complete forward log |
| Week 12 small-money pilot | UI readiness concepts exist | Not eligible | Day 77 gates have not run |

## 11. Completed, Partial, Not Started, Frozen

### Completed for Day 1 baseline

- Repository, architecture, API group, database, provider, strategy, UI, script,
  and deployment inventory.
- Full Python test and frontend build baseline.
- Current-worktree plaintext credential scan.
- Canonical 84-day execution plan created.

### Partial

- Longbridge realtime data.
- Market clock and bar freshness.
- Historical features/labels/backtests.
- AI structured plans and hard vetoes.
- Journal and readiness workflows.
- Consumer workbench and responsive UI.

### Not started in the formal evidence chain

- Immutable strategy version/config hash.
- Approved point-in-time market-data contract and universe.
- Approved no-look-ahead, cost-aware walk-forward validation.
- Formal strategy-validation records.
- Completed AI action outcomes.
- Fifteen trading days of forward observation.
- Production backend/database/monitoring/restore proof.

### Frozen

- Options, crypto, MSTR feature expansion, extra strategy optimization,
  additional agents, automatic orders, broker/account/position access, social
  features, native applications, and unrelated UI redesign.

## 12. Day 1 Decision

The project is formally reset to Day 1. Existing advanced code is preserved as
inventory and potential leverage, but receives credit only when the roadmap
prerequisites and evidence gates are satisfied.

Day 2 may begin only after this audit, the canonical plan, the daily log, the
green test/build baseline, the credential scan, and a rollbackable Git commit
are present on `main`.
