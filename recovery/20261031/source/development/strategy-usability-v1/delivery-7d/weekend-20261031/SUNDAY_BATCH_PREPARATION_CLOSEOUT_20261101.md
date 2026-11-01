# November 1: bounded preparation continuation

Recorded after the 08:46:40 UTC baseline. This is isolated repair work, not a
release, market-window result, or replacement for the original seven-day FAIL.
The user remains on this computer. Accepted payload and five business stores
were not edited, started, copied or migrated.

## Implemented code

All paths below are relative to `../opening-first-hour/`.

1. `minute_resolution_plan.py` and `first_hour_minute_decisions.py`: bounded
   immutable native-version selection reuse. Exact raw/eligible identities,
   method, policy and selector identities participate in the key. Mutable input
   bypasses reuse. Method validity and eligibility remain current checks; no
   cached authority, timestamp renewal or suppression of new contradictions.
2. `first_hour_coverage.py`, `first_hour_projection.py`, `assembly/bootstrap.py`:
   compute content-only factor grades when an immutable projection row arrives.
   Reconciliation still uses original time, deadline, scope and coverage logic.
   Changed validator identities fall back to the original implementation.
   Projection deltas, watermark and resets retain their existing semantics.
3. `first_hour_minute_decisions.py` and `first_hour_runtime.py`: prepare decisions
   for the existing maximum eight-task batch outside the write transaction,
   then use one existing append transaction. The 500-row limit and original
   lock budget remain unchanged. Oversized batches fall back before writing.
   Reuse ends at the next real time/method/receipt/deadline boundary; rollback
   of the observed clock also forces the original path. Durable decision tokens
   and final generation/CAS checks are not replaced with cache claims.

`assembly/live_fact_topology.py` records input_batch_decision_seconds as an
additional phase, not a substitute for enqueue-to-result latency.

## Verification

`test_resolution_preparation.py` covers selection equivalence, changing native
versions, method revocation/expiry, mutable bypass, conflicts and bounded batch
write equivalence. Real Lane construction verifies durable production before
handoff and time-boundary fallback; it does not bypass initialization.
`test_coverage_preparation.py` compares exact original coverage results across
both strategies, late/early observations, revisions, missing/nonfinite factors,
and projection watermark/reset behavior.

Final affected regression: **156 passed in 16.60s**.
Raw result: `evidence/decision-batch-full-20261101.xml`.

| Actual isolated process run | Seconds | Background reads | Last queue P95 | Verdict |
| --- | ---: | ---: | ---: | --- |
| sunday-resolution-plan-short9-20261101 | 240.360 | 515/515 | 10.718s | Performance FAIL |
| sunday-coverage-prepared-short10-20261101 | 240.313 | 490/490 | 9.250s | Performance FAIL |
| sunday-decision-batch-short11-20261101 | 240.234 | 499/499 | 8.438s | Performance FAIL |

These are different code versions, not two passing tests of one version. The
compressed 11-point test clock is TEST_ONLY and is not a full market hour.
Single-run differences do not establish a stable performance improvement.

Short11 enqueue-to-result P95 by point, seconds:
4.250, 4.766, 5.203, 4.657, 5.328, 5.094, 6.125, 5.656, 6.735, 6.984, 8.438.
All remain above the original 2s target. No timeout, rate or thread limits
were increased. A new matching 3600s acceptance was NOT_RUN because the two
passing same-version short-test gate remains unmet.

Short11 restored 100/100 pending tasks with original deadlines. Source and
frontend hashes stayed unchanged throughout the run; owned child-process list
was empty after cleanup. Background successes do not erase HTTP failure records.
Its nine failed HTTP requests have exact request/forward/process evidence:
six CONNECT traces target the deliberately terminated backend, and three target
the replacement process before its cold snapshots become ready. These findings
do not retroactively identify historical failures whose originals are missing,
nor prove a Windows/OS root cause.

Browser `signal_delivery_accepted=false` remains a failed/unfulfilled separate
gate. There is no claim of natural opportunity, actual-market S0/S1 completion,
full webpage signal delivery, or qualified research publication from this test.
The analysis includes an extra recovery/test record; its 4401 record count must
not be used as the two-strategy fixed 4400-position window denominator.

## Evidence and actual state

Raw reports are in `source/evidence/new-machine-20261008/<run>/topology_report.json`
under the project root. Each run's bounded summary and analysis are also in
this directory's `evidence/` with `<run>-summary.json` and `<run>-analysis.json`.
They retain request association, per-point counts and incomplete reasons.

`evidence/baseline-20261101T084640Z.json` is a sequential metadata-only check:
no checked listeners; original release/recovery hashes match. It did not open
business databases. Production remains not restored. No SDK or paid API request
was sent. Previously postponed private key configuration remains postponed.

## Remaining delivery gate

The next bounded repair must target measured residual admission preparation,
including repeated reads/hash validation, while preserving mutation detection,
source/method expiry, clock boundaries, durable generation and CAS. Do not claim
that immutable selection or grade reuse alone fixed queue latency. No new
release identity is submitted while the same-version short gate is failing.
Restore, any expired permissions and exact publication remain consolidated user
decisions later. The original seven-day verdict stays **FAIL_UNCHANGED**.

All invoked test sessions ended and were reaped. This resume does not promise
continued coding after the chat turn. Current local changes are newer than
the previously pushed GitHub commit `4b88225b44cb2f1ae32823a3d6ad7915bc1dedbd`.
