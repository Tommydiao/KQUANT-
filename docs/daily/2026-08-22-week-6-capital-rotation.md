# KQUANT v2 Week 6: Capital Rotation v0.1

Date: 2026-08-22  
Branch: `codex/kquant-v2-gap-analysis`  
Scope: materialize a point-in-time Capital Rotation baseline from the aligned
Theme Taxonomy, expose it through the read-only API, and verify concentration
and stress behavior before Leadership work.

## 1. Objective And Completion

Completion: 100% of the Week 6 implementation scope.

- A fresh rotation run was generated against the current Registry and current
  Theme Taxonomy rather than reusing the stale August 17 artifact.
- The run uses Longbridge daily candles, a market-bar-close availability bound,
  and an explicit `future_data_used=false` contract.
- Themes with fewer than five eligible members are excluded from ranking.
- Member contributions are capped and the top-member removal stress test is
  recorded for every ranked theme.
- The ranking API is read-only and returns lineage for both the rotation run and
  the taxonomy run.

## 2. Materialized Result

| Metric | Result |
| --- | --- |
| Rotation version | `capital_rotation_v0.1.0` |
| Rotation run | `crr_3ef3d56258c7b1960e5c` |
| Taxonomy run | `ttr_e73e20778fd20572bf3c` |
| Registry | `usr_eb0a628fbc333f57ea6c` |
| As-of time | `2026-08-22T04:52:33.421762+00:00` |
| Data source | `longbridge_candles` |
| Ranked themes | 17 |
| Minimum members | 5 |
| Single-member cap | 15% |
| Maximum observed top-member contribution | 10% |
| Stress direction flips | 5 |
| Unreasonable stress flips | 0 |
| Future data used | false |

The five direction flips are retained as stress observations, not silently
discarded. None met the configured unreasonable-flip condition. The leading
themes are a current cross-sectional research ranking; this is not an OOS
return claim and must not be shown as a prediction probability.

## 3. Code, API, And Acceptance

- `latest_capital_rotation()` now rejects a run whose taxonomy lineage is not
  the current materialized taxonomy.
- `GET /api/themes/ranking` returns `materialized`, the fresh run ID, 17 score
  records, taxonomy alignment, and `read_only_research=true`.
- `GET /api/themes/audit` returns `pass`, aligned Registry IDs, 99.32% theme
  mapping, 25 definitions, and an explicit two-symbol review queue.
- Targeted Theme, Rotation, and Dashboard contract tests: `22 passed`.
- Current full Python regression: `234 passed in 451.66s`.
- Frontend: `npm.cmd test -- --run`, `2 passed`; `npm.cmd run build` passed
  with the existing large-chunk warning.
- Read-only boundary: passed with 101 registered routes and no forbidden
  account, position, order, broker, or options-order route.
- `git diff --check`: passed.
- HTTP checks were run against the restarted local FastAPI service after the
  fresh rotation run; the ranking payload contained 17 score records.

## 4. Leakage And Technical Risks

- The rotation run is point-in-time bounded by the latest closed market bar;
  forming bars and future returns are not inputs.
- The current ranking is not yet a predictive model and has no OOS performance
  evidence. It is only the deterministic baseline required by Week 6.
- Five stress direction flips indicate that theme direction can be sensitive to
  removing the leading member; this is recorded for later stability analysis.
- Historical Longbridge backfill remains quota-limited. The current 99.32%
  daily/1H live coverage does not imply a complete historical training set.

## 5. Go / No-Go

**Capital Rotation Gate: GO.** Current lineage, PIT replay, five-member
minimum, concentration cap, stress audit, and read-only API checks pass.

**Overall research/model Gate: NO_GO.** No OOS model gate has passed, the
historical dataset remains limited to 99 eligible symbols, and no required
forward Shadow Observation window has completed.

## 6. Commits And Rollback Points

- Week 4 data boundary: `884bc57`
- Week 5 taxonomy audit: `f3e3dfb`
- Stale downstream lineage guard: `528e16d`
- This report is the Week 6 audit record; it is not a substitute for a
  production data snapshot or model result.
- All changes are on `codex/kquant-v2-gap-analysis`; no remote push was made.

## 7. Next Week

Build the Dataset Builder, versioned feature/label contracts, rolling
train/validation/test splits, purge and holding-period embargo, artifact
hashes, and reproducible naive/CRS/Logistic baselines. The test partition must
be immutable and fail closed on any version or hash mismatch.
