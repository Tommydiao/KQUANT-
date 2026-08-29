# KQUANT v2 Week 9 Addendum: Leadership Lineage Recheck

Date: 2026-08-22  
Branch: `codex/kquant-v2-gap-analysis`  
Scope: prevent an old Leadership snapshot from being presented after a new
Theme Taxonomy or Capital Rotation snapshot is materialized.

## Result

The current taxonomy and rotation changed after the original Leadership run.
The read path now returns `stale_rotation` with an empty leader list and the
old/new rotation and taxonomy IDs instead of serving the old cross-section as
current research.

A fresh read-only Leadership snapshot was then materialized from the current
rotation:

| Metric | Result |
| --- | --- |
| Leadership run | `ldr_2e39a4a1d5d3228b0cc5` |
| Rotation run | `crr_3ef3d56258c7b1960e5c` |
| Taxonomy run | `ttr_e73e20778fd20572bf3c` |
| Unique symbols | 293 |
| Future data used | false |
| State counts | Leader 117, Emerging 92, Neutral 80, Weakening 203 |

The state counts are descriptive same-timestamp research output. They are not
win rate, forecast probability, or OOS portfolio performance.

## Tests And Gate

- Leadership, Capital Rotation, Dashboard, Stock Quant, and validation
  lineage tests: `38 passed` in the focused regression after the change.
- The stale Stock Quant dataset, ranking, validation and readiness paths now
  fail closed on a Registry mismatch.
- Leadership implementation Gate: **GO**.
- OOS leadership performance Gate: **NO_GO**; no cost-adjusted multi-fold
  Rank IC or portfolio comparison has been completed.
- Real-money Gate: **NO_GO**.

## Next Action

Any new universe repair or taxonomy/rotation run must be followed by an
explicitly materialized Leadership run. The next remaining work is to seal a
current aligned Stock Quant dataset before interpreting validation metrics.
