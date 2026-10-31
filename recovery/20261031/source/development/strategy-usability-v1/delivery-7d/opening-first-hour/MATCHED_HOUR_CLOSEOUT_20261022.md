# Eleven-Point Implementation and Matching-Hour Closeout

Updated2026-10-22 after14:51Z. Deadline remains2026-10-23T14:30:22Z.
Result: implementation delivered and matching hour completed; overall acceptance FAIL.
No new production launch approval is requested or implied.

## Exact scope

TEST_ONLY candidate identity:
9842dd0776c7389707ded700523bca1dabf47950623b9e18fef98ec98d4a3835

Evidence directory, relative to project root:
source/evidence/new-machine-20261008/first-hour-matched-hour-20261022/

candidate_manifest.json binds source and frontend inventories. Both unchanged checks
are true. The isolated assembly uses actual Supervisor.start/Worker construction,
separate backend/Gateway, three compiled browser pages, synthetic source and clock
transport,75900legacy revisions and eleven300second-spaced checkpoints.
No real SDK connection, paid model call or production write was added.

## Implemented and exercised

- Candidate Signals heading reads09:35-10:25ET,11checkpoints,10:30cutoff.
  Old policy heading is preserved. Both isolated frontend builds passed.
- First-hour policy/store/pipeline/reference/current/status-worker modules are
  installed in actual spawned test processes; no production payload is patched.
- The existing current-card materialized projection repair is retained.
- Functional browser short at browser-20261022T134137Z exercised the first-hour
  card, concrete TEST_ONLY reference, S0/S1 difference and original expiry.
  This is not a real-market signal.23affected regressions passed.
- New-window manual registration remains rejected with STRATEGY_VERSION_MISMATCH.
  A separately labelled legacy fixture passed authenticated entry, duplicate,
  partial exit and session lifecycle. No new holding policy was accepted.

## Matching-hour result

Actual duration3601.468seconds. Eleven checkpoints captured200applicable direction
positions per variant, plus22identity exclusions per checkpoint. Observed positions:
S0=2200/2200; S1=2200/2200; unexplained_missing=[] at every captured checkpoint.
Captured complete positions: S0=2134/2200; S1=2130/2200. Raw records=2314each,
including revisions. These are synthetic checkpoint snapshots, not a final real
window90percent claim or per-object-all-points completeness assertion. The first
snapshot includes preparation/revision timing; injected AAPL source conflicts remain
INCOMPLETE instead of being silently resolved. Do not drop them from denominators.

100pending jobs restored after killing the test backend, with original deadlines.
The10:30cutoff reconciliation records0new evaluations at/after cutoff.
All test child processes exited;8193/8194 are no longer listening.

Enqueue-to-commit P95 seconds, points1through11:
10.875,13.578,11.985,12.625,14.719,15.578,25.297,27.609,31.688,30.891,36.281.
Each point has100timing samples. This is NOT receive-to-calculation latency.
The2second engineering target remains FAIL. Smaller compute-only measurements do
not replace end-to-end measurements. Source preparation and enqueue are separately
recorded in TEST_ONLY-checkpoint-1.json through TEST_ONLY-checkpoint-11.json.

Background transport:5440attempts,5436successes,4failures including2deadlines.
Two current_cards failures measured338.648ms and324.237ms against300ms budget.
Request IDs:3b219c4522ad4767b7f6d85d2250540d,144e6889779b46a7b8ebbf9f214a202c,
fa6fc631fbd549d7a9a024e435b7dee8,856afdfdb5a4452fa4698655b14062a4.
TEST_ONLY-query-accounting.json has complete parent-process denominators. This does
not assert independent module-file proof for every disposable child process.

Browser: three pages,115refreshes each,4HTTP503 still require attribution:
TEST_ONLY-browser-10994,11008,10995,11009 at14:40:14-15Z, on status/current.
4370explicit TEST_ONLY_UNMOUNTED route observations are separate exclusions and
are not successful requests. Original browser-report.json preserves all records.
Nine other harness HTTP503 match the injected recovery contract; their records
still say causal_attribution_proven=false. Time overlap alone is not root-cause proof.

The harness writes observation_assembly_pass=true for its narrow assembly/degraded
boundary before the wrapper appends BACKGROUND_QUERY_FAILURES. That boolean and
the console's earlier errors=[] are NOT the final overall verdict. Use final errors,
browser observations and performance together: overall FAIL, not release-ready.

## Protected production

At14:51:15Z actual live endpoint still reports198444f784fb3ada, backendPID30976,
GatewayPID27008, process identity verified, heartbeat age9.059seconds and8001/8020.
Worker loop974304, WAIT_NEXT_CYCLE, last persisted bar14:51Z. No restart/switch.
Its projection tasks report POLICY_CONFIG_MISSING and worker retains an
OperationalError field. HTTP/worker progress therefore does not establish complete
research availability. Production's actual authenticated page was not retested here.
The test field production_restored=false means this isolated run did not perform
a production restoration; it is not evidence that the protected service is offline.

## Concrete remaining work

1. Attribute the4browser failures at slot11 and4background failures without
   granting exemptions based only on injection overlap. Keep budgets unchanged.
2. Profile and reduce repeated policy construction/read-only preparation. Existing
   source profiles show repeated first_hour_journal.load_policy/first_hour.policies
   calls; this is a measured hotspot, not proof of the whole latency cause.
   Read-only EXPLAIN uses trend_current_time covering index, so a missing-index
   claim is not supported. Preserve CAS, generation and original deadlines.
3. Review first-hour detail routing: existing isOpeningPolicy recognizes older
   IDs; the short browser test did not click Detail. Do not claim that path passed.
4. Preserve this exact failed hour. Changed sources/builds need their own identity
   and affected short tests before another justified matching run; do not repeat
   an unchanged expensive hour. Consolidate exact O-LAUNCH only when ready.

## Evidence map

- candidate_manifest.json: exact candidate and source/build inventory.
- topology_report.json: constructor assembly, checkpoints, recovery and failures.
- TEST_ONLY-query-accounting.json: all5440background attempts and failed request IDs.
- browser-report.json: actual three-page observations and HTTP failures.
- TEST_ONLY-cutoff-reconciliation.json: cutoff check.
- TEST_ONLY-signal-3307s.png: corrected heading and slot11snapshot with degradation warnings.
- TEST_ONLY-loaded-modules-*.json: actual supervisor module paths.
- TEST_ONLY-source-profile-38796-enqueue-*.txt: enqueue hotspot profiles.

Natural signals, real11point market delivery, receive-to-page latency and LLM real
capability are NOT established by this test. No gains or option returns are claimed.
