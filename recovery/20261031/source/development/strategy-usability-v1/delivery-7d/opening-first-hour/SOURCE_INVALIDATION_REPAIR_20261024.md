# Source invalidation repair and affected topology results

Seven-day verdict: FAIL (unchanged). Overall repair is NOT COMPLETE.
No production restart, renewal, release, paid request, or business-data write.
Actual entry still selects198444f784fb3ada. Read-only listener check found no
8001/8020 or isolated8193/8194 listeners before testing. Workspace is not a Git
repository; source identities are recorded by each topology manifest instead.

## Code implemented

Source publication previously built a reference outside the lane condition and
then wrote it onto the current latest input. A concurrent newer quote could be
replaced with reference data derived from an earlier job. source_facts_ready now
only increments the input epoch and wakes original unexpired slots under the
existing condition. It does not overwrite native inputs or perform source I/O.
Computation still rebuilds durable source facts before fingerprint/CAS checks.

The constructor-based source-notification regression failed before the fix and
passes after it. It verifies preserved native input, epoch advancement, and no
reference build on the notification path. It is not a full causal replay of the
historical four-symbol timing interleaving.

Removed eager fallback hashing from input_fingerprint: a supplied decision_hash
is used without recomputing the entire decision. Missing hashes still use the
original digest. Added regression checks equivalent output and fallback behavior.
No acceptance validation was removed.33 affected pytest tests pass.

## Completed runs

All evidence below is in source/evidence/new-machine-20261008. These runs use
TEST_ONLY inputs, clocks and transport; they are NOT real market results.

| Evidence directory | Background reads | First-point complete S0/S1 | Last queue P95 |
| --- | --- | --- | --- |
| first-hour-source-invalidation-20261024 | 491/491 | 200/198 out of200 each | 8.765s |
| first-hour-lazy-fingerprint-20261024 | 478/478 | 200/198 out of200 each | 9.812s |

Both runs have eleven checkpoints, unchanged tested source/frontend hashes and
no surviving test children. The prior CYN/DGP/DLR/DUK first-point gaps did not
recur. AAPL's S1 native-basis exclusions and later injected conflict remain;
they are not waived or removed from the denominator. Raw historical failures
remain intact. The digest optimization has NOT demonstrated a stable end-to-end
performance improvement. Neither run passes performance or observation assembly.

Both browser reports contain no non-isolation API failures. This does NOT mean
all HTTP requests succeeded: the second run failed with9 independent probe503s.
Six responses correspond to shared CONNECT failures (upstream IDs
5d52896aff014d4f8b07a5f25dfca46b and8a1c2ae817e24ded91df9e83b27092dc);
three compact responses are TREND_STATUS_UNAVAILABLE. The classifier retains
UNEXPLAINED and causal_attribution_proven=false despite injected-recovery overlap.
See topology_report.json/http_failure_classification and
TEST_ONLY-gateway-transport.json. Historical four503 are not closed by these runs.

## Unfinished gates and exact continuation

The requested complete plan has not been completed. No matching hour was started:
two passing short runs have NOT been achieved. No accurate release approval is
being requested on failed evidence. All test sessions have exited.

Next work must be actual local preparation-path replacement, not another unchanged
hour: align admission and compute source fingerprints, instrument readmission
counts by cause, and share bounded immutable preparation only within matching
minute/source/method/clock generations. Preserve fresh source validation, CAS,
original deadlines, full scope and missing-input semantics. Reproduce concurrent
source publication during admission/compute/WAIT_INPUT using real constructors.

Also close the new probe503 attribution using upstream IDs, actual backend
lifecycle and readiness evidence; do not classify by time overlap alone.
Existing snapshot event coalescing remains; no rate, timeout or thread increase.
Once affected correctness/performance shorts genuinely pass twice on one source
identity, freeze and run3600seconds. Restore/permission renewals/exact launch
acceptance remain one consolidated user decision after engineering readiness.
