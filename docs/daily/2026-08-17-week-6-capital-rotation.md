# KQUANT v2 Week 6 Report: Capital Rotation V0.1

Date: 2026-08-17
Branch: `codex/kquant-v2-gap-analysis`
Scope: Capital Rotation V0.1 deterministic baseline. No Options Engine, broker, account, position, or order work was added.

## 1. Goal And Completion

The Week 6 objective was to build a point-in-time theme rotation baseline after the taxonomy Gate passed. Implementation completion is 100% for the planned code surface:

- versioned Capital Rotation schema and migration;
- deterministic theme score, member weights, stress test, and audit payload;
- CLI materialization and read-only API routes;
- Settings-page theme rotation overview;
- PIT, concentration, future-data perturbation, and dashboard regression coverage.

## 2. Modules, Schema, API, And UI

Added:

- `kquant/capital_rotation.py`
- Schema migration v6: `capital_rotation_runs`, `capital_rotation_scores`, `capital_rotation_members`
- CLI: `run-capital-rotation`, `capital-rotation-status`
- `GET /api/themes/ranking`
- `GET /api/themes/{theme_id}` now includes a read-only `capital_rotation` section when ranked
- Settings page Capital Rotation baseline card with source, ranking, member count, and stress diagnostics

The score is based on closed Longbridge daily bars only. It combines 5-day return, relative strength versus SPY, 5-day acceleration, breadth, dollar volume, and positive-day persistence. Themes with fewer than five eligible members do not rank. A 15% maximum member contribution is enforced; at least seven eligible members are required for a normalized capped-weight score.

The Longbridge adapter also corrected the SDK's naive local `datetime` values: they are now interpreted as `Asia/Shanghai` and converted to UTC at the provider boundary. Other timezone-aware and Unix timestamps retain the existing UTC contract.

## 3. Data And Quality

The live SQLite database is `work/kquant_us.sqlite3` and is at Schema v6.

- Universe: 296 symbols
- Longbridge daily coverage: 293/296, 98.99%
- Longbridge 1H coverage: 294/296, 99.32%
- Materialized themes: 17 ranked themes
- Rotation source: `longbridge_candles`
- Fixed PIT rerun content hash: `c67d1c5de0573df81c9dcd7df3fd415f498377b5662faac978f37e5e4d20b89e`
- The same `as_of_time=2026-08-17T15:00:00+00:00` produced the same hash on two runs
- Highest member contribution: 10%, below the 15% cap

The real-time smoke request returned `provider=longbridge`, `source_type=longbridge_realtime_snapshot`, valid BBO, and `longbridge_candles`. After the timestamp fix, `future_time_count=0`. Forming intraday bars still block buy eligibility by design.

## 4. Verification

- Python: `174 passed`, one existing Starlette deprecation warning
- Frontend: `npm.cmd test -- --run`, 2 passed
- Frontend: `npm.cmd run build`, passed; existing 529 kB chunk warning remains
- Read-only boundary: passed; 85 registered routes, no forbidden trade routes
- `git diff --check`: passed
- Browser smoke: desktop Settings shows rotation ranking; desktop research rail is visible; mobile viewport exposes the Deep Research navigation/drawer path
- Backup before migration: verified local SQLite backup and restore drill passed; active database was not overwritten by the drill

## 5. Risks And Leakage Controls

- `fetched_at <= as_of_time` and `open_time <= as_of_time` are both required for the rotation dataset.
- Forming candles are excluded from the baseline.
- Taxonomy membership comes from the materialized point-in-time taxonomy run, not today's ad hoc tags.
- The two raw stress direction flips are recorded as caution diagnostics for borderline themes; they are not silently discarded.
- Both flips are near the neutral score line and neither meets the explicit `stress_unreasonable_flip` rule. This remains a validation item for Week 7 rather than a performance claim.
- No historical return, backtest, OOS, or forward performance has been inferred from this score.

## 6. Model And Strategy Result

This is a deterministic research baseline, not a predictive model and not a trading result. The current live ranking has `theme.technology_infrastructure` at the top with a score of approximately 77.5 in the latest materialization. The result is descriptive and point-in-time; it must not be presented as a probability, win rate, or expected live return.

## 7. Go / No-Go

**Week 6 Gate: PASS WITH CAUTION.**

- PIT rerun consistency: PASS
- Minimum theme membership rule: PASS
- Single-member contribution cap: PASS
- Unreasonable stress flips: 0, PASS
- Borderline stress flips: 2, retained as caution diagnostics

**Product / real-money status: NO-GO.** Capital Rotation has no permission to bypass data quality, strategy, or future OOS Gates. KQUANT remains a read-only research and shadow-observation system.

## 8. Next Week

Week 7 will build Dataset Builder, feature/label schema versions, rolling splits, purge and holding-period embargo, immutable test partitions, model artifact registry, and reproducibility checks. The baseline comparison will include naive, Capital Rotation rule, and Logistic models; no test partition will be used for parameter selection.
