# Implementation corrections (no strategy parameter search)

## 2026-09-05 initial integration

The initial `dev_A_base_v1` real-data replay is retained as a preliminary
development result, not a final acceptance run. Integration review identified:

- Scenario and exchange-filter hashes were not checked on portfolio restore.
- An immediate quote-based entry-gap exit used ask rather than bid.
- A range entry-gap stop did not invalidate its box.
- Candidate policy hashes needed to bind the controlling specification bytes,
  not only budget and cost settings; old config artifacts remain retained.
- Closed-bar decisions needed per-event provenance for rejection auditing.

Corrected runs use new run IDs. No thresholds, targets, symbols, time windows,
or costs were changed. The failed bounded forward startup `engineering_A_v1`
is retained; its writer-lock integration failed before market consumption.

Historical exposure is unknown and treated as exposed for all development
runs. No historical result from this sprint proves independent performance.

## Final integration corrections

The v3 outputs and selection are retained. Selection was archived as
`candidate_selection_v3_superseded.json` before final corrected reruns.
The candidate set and all thresholds remain unchanged.

- Stress sizing uses stressed projected stop loss; net R keeps BASE unit risk.
- Entry suppression cancels already reserved entries before fills.
- Old UTC day's final-candle risk is checked before resetting the daily baseline;
  next-day opening marks establish the next baseline before open protection.
- Continuity gates inspect actual gap lists rather than PARTIAL research eligibility.
- Pure quote updates are committed in five-second batches; fills, risk events
  and closed bars commit immediately with their consumed quote/checkpoint evidence.
- Snapshot restore validates scenario, rules and source hashes; stopped runs
  clear their stop flag only while holding the candidate writer lock.

The read-only original-store audit established that the full frozen history
overlaps prior published backtests. The later segment remains unopened.
