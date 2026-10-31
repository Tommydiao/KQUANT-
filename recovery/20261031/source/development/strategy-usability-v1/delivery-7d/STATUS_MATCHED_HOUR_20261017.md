# Status Reliability: Matching Hour Completed, Release Not Ready

Updated 2026-10-17 12:52 Beijing. This is an execution result, not a new plan.
Fixed T0 remains 2026-10-16T14:30:22Z; deadline remains 2026-10-23T14:30:22Z.

## Implemented and Frozen

Unpublished candidate `local-candidate-45492b7b0b7428ca` has eight production
modules. Payload SHA-256:
`607f0bb3593f3679689ab8f4749e4d97e3f862afbb56b4a263f3c0ec9d0864e6`.
Projection SHA-256:
`95159472898006281e807ca244ce36c4b0dd6ccf52794b85b50141a3778b671f`.

- Legacy status reuses validated calendar context and a covering metadata index.
  Same-bar revisions are grouped before evidence decoding; older scope/policy
  fallback is retained. The first actual topology short exposed repeated decoding
  of 75,900 synthetic revisions; the fix is covered by equivalence regressions.
- Startup-only main-store WAL preparation mitigates reproduced DELETE-mode
  reader/writer contention. It opens an existing file with mode=rw, verifies the
  result and fails closed. The actual production lock holder remains UNKNOWN.
- Exact minute-index restart validation retains the existing research index and
  rejects wrong-role/extra-index/schema drift. No business database was replaced.
- Canonical decisions reuse identical digests/comparison keys within a resolve
  call. Duplicate inputs, order and source semantics are preserved; source proof
  checks and original deadlines are not relaxed.
- The actual isolated API/Supervisor/Worker harness now includes the legacy
  background lane and audits all background query attempts, not only HTTP results.

The final affected-source regression reports are
`legacy-status-fix/tests-source-digest.xml` (157 passed, two explicit skips) and
`tests-digest-equivalence-corrected.xml` (43 passed, overlapping scope; do not sum).
Failed intermediate reports remain available. Production code was not hot edited.

## Matching Hour

Read `legacy-status-fix/hour-4549-summary.json` and its hash-linked original
`source/evidence/new-machine-20261008/status-reliability-hour-4549-20261017/topology_report.json`.

- Completed 3,600.438 seconds; source and frontend identities unchanged.
- Five checkpoints each registered 222 directions, excluded 22 unresolved identity
  directions and evaluated 200; no unexplained missing directions. TEST_ONLY
  conflict cases retained their blocked outcomes. These are not market counts.
- 100 pending jobs restored after isolated process failure, all original deadlines
  preserved. No test child processes remained after cleanup.
- Three compiled browser pages, 116 refreshes each; no browser problem entries.
  Actual authenticated HTTP handlers passed entry, duplicate, partial-exit,
  expiry and relogin tests with synthetic contracts. No natural delivery claim.
- 5,426 background queries: 5,424 successful, two failures, zero process deadlines.
  Legacy 704/704; compact 1,237/1,237; current cards 3,483/3,485.
- The two current-card failures exceeded the existing 0.3-second SQL budget at
  319.011 and 324.239ms. They are counted, not exempted by injection-time overlap.
  Request IDs: `c96ba51d1ce8418a874156b392744ec0` and
  `ec04ab47baa744ce86543f794df32604`.
- HTTP has nine specifically matched injected recovery errors. This does not
  erase the two independently counted background failures.
- Queue-to-commit P95 by checkpoint: 4.281 / 5.078 / 6.735 / 7.906 / 9.843 seconds.
  The two-second target FAILS. Individual calculation durations cannot replace
  this denominator or real receive-to-compute measurement.

The original harness assembly flag was computed before background accounting.
It is NOT the combined verdict. Comprehensive reliability FAIL, performance FAIL,
release ready FALSE. The hour is complete, not passed. No new approval requested.

## Preserved Live Service

Accepted d4f4 remains unchanged. Read its
`runtime-evidence-20261017T044848Z.json`: all twelve checked hashes match, worker
7,012 loops, last cycle 04:48:39Z, WAIT_MARKET. PID creation identities still match
launcher32524/backend13792/gateway31476. Correct backend `/api/health/live` returned
online with fresh heartbeat and the same run session at12:49 Beijing.

Its cumulative status denominator is 13,686 attempts, 12,335 successes,
1,351 failures and 1,219 deadlines. This is the OLD live implementation, not a
deployed fix. An unauthenticated Gateway request returned401 as expected; this is
not evidence that the user's confirmed browser login failed. The initial direct
backend probe used a Gateway path and returned404; the correct backend path then
passed. No credentials were read or reset.

## Narrow Remaining Work

Current-card budget failure and cumulative queue delay remain engineering work,
not missing OWNER choices. `benchmark_current_query.py` tested a materialized
compact CTE against existing TEST_ONLY data: identical results but slower, so it
was rejected and NOT added to the candidate. Keep this negative experiment.

Next continue from the failed request stages and existing input/commit profile;
replace only the measured current-card read or repeated input preparation, keep
the same timeout/source/deadline rules, and run affected short regressions before
any new matching hour. Do not repeat an unchanged hour, borrow d4f4 approval or
request approval for a supposedly fixed release. The frozen4549 artifacts and
hour remain an immutable failed baseline; subsequent code needs a new identity.

All foreground test processes are reaped. Only the intended accepted live service
continues. This pointer is not a background coding scheduler. No F-drive access,
new SDK connection, production database write, new Signal, order or fee occurred.
