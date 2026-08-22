# KQUANT v2 Week 5: Theme Taxonomy v1

Date: 2026-08-22  
Branch: `codex/kquant-v2-gap-analysis`  
Scope: convert flat point-in-time metadata into a governed taxonomy and stop
downstream snapshots from consuming a different Registry.

## 1. Objective And Completion

Completion: 100% of the Week 5 implementation scope.

- Taxonomy definitions are versioned and content-addressed.
- Dimensions are explicit: `theme`, `industry`, `risk_style`, `liquidity`,
  and `instrument`.
- Definitions support aliases, optional parent references, status, effective
  dates, rule evidence, confidence, weights, and review status.
- Unmapped symbols remain visible as an explicit review queue; they are not
  silently assigned to a theme.
- The latest taxonomy and Capital Rotation reads now verify Registry lineage.
  A stale snapshot is returned as `stale_registry` or `stale_taxonomy` and
  cannot be consumed as the current research state.

## 2. Code, Schema, API, And UI

- Hardened `kquant/theme_taxonomy.py` validation for dimensions, statuses,
  aliases, parent references, rules, and effective dates.
- Added `taxonomy_audit()` and `GET /api/themes/audit`.
- Added Registry alignment details to `GET /api/themes`.
- Added an audit summary to the Settings workspace, including Registry
  alignment and membership review statuses.
- Added lineage checks to `latest_capital_rotation()` and a stale result state
  before Leadership can consume an old taxonomy run.
- Existing tables remain compatible; no broker, account, position, order, or
  Options Engine route was added.

## 3. Materialized Result

The current taxonomy was explicitly rebuilt against Registry
`usr_eb0a628fbc333f57ea6c`:

| Metric | Result |
| --- | --- |
| Taxonomy version | `theme_taxonomy_v1.0.1` |
| Taxonomy run | `ttr_e73e20778fd20572bf3c` |
| Registry members | 296 |
| Theme-mapped symbols | 294 / 296 (99.32%) |
| Definitions | 25 |
| Memberships | 749 auto-mapped, 2 needs-review |
| Point-in-time | true |

The 2 unmapped symbols are an explicit review state. The 95% taxonomy mapping
Gate passes; this is classification coverage, not strategy performance.

## 4. Tests And Browser/API Acceptance

- Theme, Capital Rotation, and Dashboard contract tests: `22 passed`.
- Current full Python regression: `234 passed in 451.66s`.
- Frontend: `npm.cmd test -- --run`, `2 passed`; `npm.cmd run build` passed
  with the existing large-chunk warning.
- Read-only boundary: passed with 101 registered routes and no forbidden
  account, position, order, broker, or options-order route.
- `git diff --check`: passed.
- HTTP checks returned `/api/themes` as `materialized`,
  `/api/themes/audit` as `pass`, and `registry_aligned=true`.
- Old Capital Rotation data is now explicitly rejected as `stale_taxonomy`
  until a current run is materialized.

## 5. Leakage And Technical Risks

- Taxonomy rules use only point-in-time universe metadata and do not read
  forward returns.
- A current Registry change invalidates downstream snapshots by lineage rather
  than rewriting their historical records.
- Historical membership before observed snapshots remains
  `survivorship_limited`.
- Two members still need manual classification review.
- Longbridge quota `301607` continues to block historical backfill, so theme
  membership quality is not evidence of predictive alpha.

## 6. Go / No-Go

**Taxonomy Gate: GO.** Mapping coverage, effective dates, explicit fallback,
and Registry alignment pass.

**Overall research/model Gate: NO_GO.** Historical validation is only 99/296
symbols, no OOS model gate is passed, and no forward Shadow Observation window
has completed.

## 7. Commits And Rollback Points

- Week 4 data boundary: `884bc57`
- Week 5 taxonomy audit: `f3e3dfb`
- Stale downstream lineage guard: `528e16d`
- All changes are on `codex/kquant-v2-gap-analysis`; no remote push was made.

## 8. Next Week

Materialize a fresh `Capital Rotation v0.1` run from
`ttr_e73e20778fd20572bf3c`, then verify the 5-member minimum, 15% top-member
cap, stress-without-leader test, same-timestamp PIT replay, and theme ranking
API before Leadership work begins.
