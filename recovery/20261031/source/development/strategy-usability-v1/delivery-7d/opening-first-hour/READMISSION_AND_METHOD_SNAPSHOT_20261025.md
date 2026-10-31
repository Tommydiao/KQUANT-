# Readmission and bounded method validation: execution evidence

Status: IN_PROGRESS / NOT READY FOR MATCHED HOUR OR RELEASE.
Historical seven-day delivery remains FAIL. No deadline reset, production restore,
permission renewal, paid request, production payload edit or business DB migration.

## Actual changes

- first_hour_minute_decisions.py: admission can consume the existing durable
  decisions already read by resolve; compute still reads current durable decisions.
- first_hour_runtime.py: readmission and admission retry use latest_inputs under
  the existing condition, retaining the original checkpoint key and deadline.
  setdefault preserves a newer pending notification. No extra worker or timeout.
- method_snapshot.py / first_hour.py: validation results are copied and shared
  only inside one calculation context, then original validators reread evidence
  before returning. Changed evidence raises SourceSnapshotChanged and enters the
  existing bounded retry path. No size/mtime shortcut, cross-calculation reuse,
  method extension or false acceptance. This is not a proven performance win.
- Affected regression suite: 39 passed, including real lane construction,
  readmission coalescing, same-size evidence changes and exception cleanup.

## Three completed isolated topologies

Evidence root: source/evidence/new-machine-20261008 (relative to project root).
All are TEST_ONLY, not real market windows. Actual process constructors, compiled
pages and isolated stores were exercised. Latest source/build identity checks true;
latest child_processes_alive is empty. A zero process exit is not a product PASS.

| Evidence directory | First S0/S1 full out of 200 each | Last queue P95 |
| --- | --- | --- |
| first-hour-shared-decision-read-20261024 | 192 / 190 | 8.609 s |
| first-hour-current-readmission-20261025 | 200 / 198 | 8.922 s |
| first-hour-method-snapshot-20261025 | 200 / 198 | 9.891 s |

Latest duration 240.156 s. Background query accounting 473/473 successful,
zero failures/deadlines. All 11 checkpoints observed; later injected AAPL
conflict remains INCOMPLETE, not a removed denominator. 100 pending restored
without extending deadlines. Recovery current/compact both FRESH after2.625s.
performance_pass=false; observation_assembly_pass=false. Matching3600s NOT RUN.

## Nine earlier 503s and four current browser 503s

Earlier first-hour-lazy-fingerprint-20261024 had three health CONNECT timeouts,
three current CONNECT timeouts and three compact TREND_STATUS_UNAVAILABLE.
The replacement's current/compact remained STALE at the5s readiness deadline;
the recovery contract therefore did not qualify. Snapshot-ready timestamp was
the end of a failed check, not proof of readiness. Do not waive these failures.
Exact historical trigger of snapshot delay remains unproven.

Latest four browser responses join exactly to two Gateway upstream IDs:

- cad43089ac29456e81b49e0f19c2fa76: current, browser88/89,
  monotonic874289.515..874290.265, CONNECT / ConnectTimeout.
- 99b4e4222aa6494c9beb488defd8ed98: compact, browser86/87,
  monotonic874289.500..874290.265, CONNECT / TimeoutError.

Gateway PID45212, killed backend23820, replacement7744. Injection began874289.187;
replacement HTTP ready874291.890; fresh snapshots874294.515.
Requests took776..779ms. Shared request IDs prove fan-out, not four upstream calls.
Transport evidence plus process timing identifies the connection phase; it does
not by itself prove historical causal attribution. Browser classification remains
HTTP_FAILURE_REQUIRES_ATTRIBUTION. Do not silently reclassify as successful reads.
Latest nine probe responses match the existing injection contract but still carry
causal_attribution_proven=false. They do not erase the earlier failed recovery.

## Exact continuation

1. Finish browser-to-Gateway-to-process attribution with existing IDs, retaining
   original path/query and request windows; never exempt by time overlap alone.
2. Measure shared preparation and canonical admission costs separately from
   calculation and commit. Latest per-symbol calculation is small while total
   queue remains9.891s: current optimization has not resolved the bottleneck.
3. Verify actual loaded module mapping before claiming method memoization benefit.
   Then implement the planned immutable generation-scoped preparation replacement,
   preserving source invalidation, native conflicts, original deadlines and CAS.
4. Require two passing same-source shorts, then immediately run matched3600s.
   No restoration/release request yet: independent engineering remains incomplete.

No promise of coding after this session. All completed test processes were reaped.
