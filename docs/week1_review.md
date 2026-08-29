# KQUANT Week 1 Review

Status: completed engineering baseline; not a trading-readiness approval

Review date: 2026-07-18

## Completion Matrix

| Day | Objective | Status | Evidence |
|---:|---|---|---|
| 1 | Current-system audit | Complete | `docs/current_system_audit.md` and daily log |
| 2 | Personal live MVP scope | Complete | `docs/personal_live_mvp.md` |
| 3 | One active strategy specification | Complete | `docs/strategy_specification.md` |
| 4 | Market-data contract | Complete | `docs/market_data_contract.md` |
| 5 | Immutable strategy versioning | Complete | `strategy_versions` schema and persistence coverage |
| 6 | Validation entry point and CI | Complete | `verify_kquant_local.ps1` and GitHub workflow |
| 7 | Week 1 review | Complete | this document |

## Decisions Locked for Week 2

1. `swing_long_v1` is the sole validation strategy. All other profiles are
   frozen, including high-beta variants, MSTR extensions, options, crypto and
   extra agents.
2. The system is US-stock/ETF, long-only and manual-execution only.
3. Longbridge is the primary read-only market-data source. Yahoo may be shown
   only as reference data and cannot support a real-money BUY conclusion.
4. UTC is the storage contract, `America/New_York` is the exchange contract,
   and completed bars are the only bars eligible to trigger a signal.
5. Signals, features, labels, validation runs and AI action events must bind to
   an immutable strategy version and configuration hash.

## Engineering Evidence

- Strategy-version tests verify deterministic hashes, immutability rejection,
  signal persistence and AI-action persistence.
- The unified verifier performs frontend build, Python tests, a repository
  credential scan and optional local readiness checks.
- GitHub Actions runs the same build/test/credential checks without requiring
  local market-data credentials.
- Final baseline verification: `213 passed`; production frontend build passed;
  plaintext credential scan passed. A Vite bundle-size warning remains logged
  as non-blocking performance debt.

## Risks Carried Forward

- Historical Longbridge availability is not yet proven across market sessions.
- Existing historical candles and labels have not yet been reconstructed under
  the new point-in-time data contract.
- `strategy_validation_runs`, `ai_action_outcomes` and the trading journal do
  not yet provide verified out-of-sample evidence.
- The UI and AI plan experience remain ahead of the evidence base and must not
  be read as a proven trading edge.
- Any Longbridge token shown in a prior screenshot must be revoked and replaced
  outside the repository before using the provider again.

## Week 2 Go / No-Go

Decision: **GO for data-foundation engineering only.**

Week 2 may implement provider health telemetry, source lineage, completed-bar
handling, trading-calendar tests, point-in-time universe membership and fault
injection. It may not relax entry thresholds, claim a tested win rate, enable
broker/account/order access, or begin a real-money pilot.
