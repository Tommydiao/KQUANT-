# Actual journal and assembly findings

This is incomplete engineering work, not release acceptance. Seven-day FAIL stays.
No production payload or business data changed; no restore, paid request or renewal.
8001/8020 had no listeners during this check. Test children were reaped.

## Implemented corrections

1. assembly/bootstrap.py now maps options_minute_decisions to the first-hour
   candidate. Previously the real child loaded recovery-null-time-followup while
   admission directly imported the new module; calculation-scope sharing was not
   connected to the consumer. The actual child now verifies the corrected mapping.
2. assembly/live_fact_topology.py profiles first_hour_journal, the actual lane
   dependency. Prior instrumentation targeted options_opening_momentum_journal,
   so its missing timing records were not proof of negligible journal overhead.
3. Regression suite after binding correction:39 passed.

## Completed evidence

Paths relative to source/evidence/new-machine-20261008:

- first-hour-bound-method-20261025:240.062 seconds; background481/481 successful;
  browser non-isolation failures0; first complete S0/S1 200/198 of200 each;
  last queue P959.078 seconds, performance FAIL. One independent client
  ConnectTimeout TEST_ONLY-7036-2-179, current endpoint, NO_OVERLAP, remains FAIL.
- first-hour-actual-journal-profile-20261025:240.110 seconds; background484/484;
  final queue P9510.078 seconds. Profiling overhead present, not an acceptance run.
  All children exited. No matching3600s run: short gates have not passed twice.

Actual replacement child6132 timing totals (overlapping phases, do not add):

| Phase/thread | Calls | Total seconds | P95 seconds |
| --- | ---: | ---: | ---: |
| checkpoint input/admission |1595|63.695|0.125|
| checkpoint input/compute |1541|33.511|0.062|
| calculation |1100|20.391|0.032|
| journal ready |355|6.421|0.109|
| journal begin |345|3.873|0.032|
| journal finish |151|6.815|0.110|

This supports prioritizing duplicate input preparation; does not prove an
immutable-preparation replacement is implemented or that contention is absent.
Decision-read EXPLAIN on prior isolated data uses trend_input_source
(session,symbol,queued_at); NVTS had55decision rows and38other journal rows.
No evidence that this query scans the entire75900 historical evaluation set.

## 503 attribution boundaries

Old lazy-fingerprint nine probe503:
- six clients report GATEWAY_UPSTREAM/CONNECT/UPSTREAM_TIMEOUT;
- three compact requests report TREND_STATUS_UNAVAILABLE. Replacement22776
  projection logs show no cached value, generation0 and pending loader age
  0.266..0.281seconds at this failure, with no loader exception recorded.
- The5s recovery readiness check later found both views STALE. That is a failed
  recovery contract, not proof that initial loading took5s or that SQLite failed.
- Probe logs lack forwarded server request IDs. Mechanism can be classified,
  but exact per-client-to-projection linkage and deeper historical cause cannot
  be reconstructed from time overlap alone. Preserve original UNEXPLAINED verdicts.

New method-snapshot four browser503 have exact server ID joins (see previous
READMISSION_AND_METHOD_SNAPSHOT_20261025.md): two shared CONNECT failures with
two consumers each, before replacement HTTP readiness. Do not change original
classification or claim four distinct upstream requests. Full fault causality
is not proven by this join alone.

## Remaining implementation, not completed

Replace repeated prepare/readmission with immutable generation-scoped preparation
inside existing lane. Validate minute generation, source version/method/clock and
original deadline; keep CAS and current conflict detection. Add controlled race
tests before another topology. Add forwarded server IDs to independent probe
evidence so future failures do not inherit the historic linkage gap. Diagnose
the new normal-interval client ConnectTimeout separately from backend503.
Two same-source passing shorts remain prerequisites for the matching hour.
