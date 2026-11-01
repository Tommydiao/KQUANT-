# November 1 Isolated Performance Repair and Handoff

## Verdict

Seven-day delivery remains **FAIL**. The isolated candidate is not approved or
deployed. Performance remains FAIL; no matching 3600-second hour was started.
This report supplements, and does not overwrite, the October31 closeout.

Latest read-only baseline: `evidence/baseline-20261101T081227Z.json`.
The entry still identifies198444f784fb3ada; no8001/8020 listeners were found,
manifest hashes match. Saved historical CimException is not new proof of its
operating-system cause. No restart, business-database read/write/copy, live SDK,
or paid API request was performed in this work.

## Implemented Isolated Changes

All paths below are relative to the sibling `opening-first-hour` overlay.
The accepted `source/development/workspace` was not changed.

- `generation_reads.py`: bounded phase-local mode=ro/query_only connections;
  original query deadlines, replacement identity checks and transaction guard.
- `method_snapshot.py`, `prepared_generation.py`: reuse path/content checks
  within a phase, revalidate before leaving it and before durable publication.
- `prepared_minutes.py`: immutable content metadata and semantic identity;
  fresh source bundles are not reused across reads. Malformed null times remain
  ineligible rather than aborting every other minute in a batch.
- `first_hour_minute_admission.py`: reuse the actual parent validator's static
  structural result for immutable minutes, with unchanged policy identity and
  live instrument/window/closed/received-time checks. Fallback remains original.
- `first_hour_minute_decisions.py`, `first_hour_journal.py`,
  `first_hour_runtime.py`: use the bounded prepared data while preserving
  source conflicts, generation/CAS, publication fence and original deadlines.
- `first_hour_summary.py`, `assembly/bootstrap.py`: compact projection selects
  needed fields before deep-copy; output and mutation isolation are tested.
- Assembly diagnostics split admission queue, compute queue, preparation,
  validation, computation and durable commit. Missing enqueue origin is null,
  not a fabricated zero; existing original latency gate remains unchanged.

No increase to timeout, concurrency, rate cap or expiry; no universe reduction.
No sixth store, new dispatcher or alternative business ledger.

## Verification and Limits

`evidence/native-structure-final-regression-20261101.xml`:129 passed in16.70s.
Native structural tests include24,768 comparisons to the parent implementation.
Earlier failing regressions and diagnostic-profile interference remain saved.
Do not add repeated test counts or call them market validation.

Latest original topology report is exported as:
`source/evidence/new-machine-20261008/sunday-native-structure-short8-20261101/topology_report.json`.
Its SHA-256 is `fb499c2f80b800f32d2d4b6756d827d3a1528bca2ff867da0caf1b5ef8053704`.
Analysis: `evidence/sunday-native-structure-short8-20261101-analysis.json`.

- Actual separate backend/Gateway and three compiled TEST_ONLY pages;240.203s,
  compressed15s checkpoint cadence, not a full market window or300s cadence.
- Background492/492 successful; no unaccounted background deadline/failure.
- 100pending restored with original deadlines; FRESH recovery2.360s;
  no owned child processes remain.
- All4400 strategy positions have latest records. S0 complete2180/2200,
  S1 complete2178/2200; remaining42 match intentional conflict/native-basis
  cases. Latest revisions are not timely-first or actual-market completion.
- Eleven enqueue-to-result P95 seconds:
  6.734,5.797,8.437,6.234,5.985,5.219,6.250,5.515,7.875,8.360,9.031.
  All fail2s. Last admission queue P95=8.516s, compute queue=0,
  preparation wall=.141s, computation=.031s, commit batch=.281s.
  Component percentiles are not additive and are not end-to-end substitutes.
- Supplemental exact request/forwarded-ID/PID classification associates six
  CONNECT errors with the deliberately terminated backend and three unavailable
  compact snapshots with replacement cold start. Original failures are retained.
  This does not recover missing evidence for old historical9/4 incidents.
- Browser reports three_real_pages=true but signal_delivery_accepted=false.
  Do not claim the actual complete Signal delivery gate passed.
- Legacy TEST_ONLY manual entry/duplicate/partial-exit/session checks ran.
  New11-point policy registration still returns STRATEGY_VERSION_MISMATCH;
  no new manual policy authorization is implied.

Local preparation samples improved from .357952s to .196740s per warmed8-asset
batch across earlier candidates. New-five-minute cold-ish sample improved from
.258057s to .233986s after static validation reuse. These are microbenchmarks,
not evidence that market latency or the2s queue gate passes.
Summary differential benchmark median .0191014s -> .00128795s over30 samples.

## Handoff and Next Work

Continue at the measured admission/preparation queue, not by widening budgets.
Preserve end-phase source/method/clock validation, WAIT_INPUT wakeups and CAS.
Run affected tests then two passing same-version short penetrations; only then
freeze and run the matching3600s/11-point assembly. Current shorts do not qualify.

Real API is NOT_RUN, no new spend. Private key setup remains postponed. Weekend
USD5 total/1per task permission is separate and expires2026-11-02T00:00+08:00;
clone or code publication does not renew it. Recovery, expired method/budget
renewals and exact new release approval must be consolidated before live use.

GitHub export contains code, builds, selected sanitized evidence and hashes.
It excludes active databases/WAL/SHM, credentials, DPAPI, browser profiles and
unreviewed historical inputs. Keep the old machine's data/recovery materials.
This is sequential file evidence, not an atomic business snapshot or complete
backup. No background coding executor or unattended continuation is promised.
