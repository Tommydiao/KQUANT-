# READY Wakeup and Transport Repair - 2026-10-24

Seven-day verdict remains FAIL. This is isolated engineering, not a release,
permission renewal, real market result, or restoration of production.

## Actual code change

`first_hour_journal.py`: duplicate admission of the same fingerprint in READY
now returns a compute wakeup without acquiring a writer or incrementing the
generation. The transaction recheck has the same rule. WAIT_INPUT, COMPLETED,
LEASED and EXPIRED are not treated as duplicate READY. begin_many still checks
current state, fingerprint and original deadline before computing.

The new regression failed before this change and passes after it. All 29 local
affected tests pass (`affected-wakeup-20261024.xml`). This demonstrates a lost
volatile-wakeup defect, not proof that it was the sole cause of the historical
AI checkpoint-2 failure. That historical missing result remains in its report.

`gateway_candidate.py`: bounded 256-record in-memory transport failure evidence
now shares the response request ID, endpoint, monotonic start/end, exception
class and transport stage. No query strings, request headers, bodies, exception
text or credentials are retained. Total count is separate from ring length.
The isolated process harness exports this ring at normal shutdown, with its
Gateway PID and actual backend port. No public endpoint was added.

## Actual process short run

Evidence directory, relative to project root:
`source/evidence/new-machine-20261008/first-hour-wakeup-trace-20261024/`

- Runtime 240.485 seconds; real separate backend/Gateway/Worker assembly,
  TEST_ONLY data/clock/transport and compiled three-page browser.
- Source and frontend hashes unchanged throughout the run.
- 520/520 background query attempts succeeded, complete process accounting.
- All eleven checkpoints observed 200/200 applicable direction positions for
  each variant. No unexplained missing positions; AI checkpoint 2 did not recur.
  Observed positions are not equivalent to complete or qualified results.
- 100 pending calculations recovered with original deadlines.
- Browser: no unmounted-route-excluded 503 this run. Four real 429 responses
  remain unclassified (browser IDs 1055-1058). Separately, 378 legacy-unmounted
  test responses are explicitly classified; they are not application successes.
- Gateway ring contains three health/live ConnectTimeout failures during the
  recorded backend crash. These are NOT the four historical browser requests.
- Original four browser 503 remain historical unresolved attribution. Earlier
  response headers establish CONNECT/UPSTREAM_TIMEOUT, but this new run cannot
  retroactively supply missing server-side causal evidence.
- Enqueue-to-commit P95 by point, seconds:
  5.235, 5.125, 6.000, 6.906, 8.719, 7.516, 9.203, 9.454, 10.203, 11.047, 11.969.
  Performance and observation assembly remain FAIL. These are not
  receive-to-compute measurements. No new matching hour was started.
- No surviving test child processes in the final topology report.

## Remaining work

The throughput defect is NOT resolved. Current evidence separates bounded
per-job input/compute/commit work from growing cumulative queue latency, but
does not justify increasing timeouts, dropping positions, or claiming a single
root cause. Next local change needs a measured queue/input preparation profile,
with admission/lease transitions retained for AI and request IDs retained for
browser failures. A non-reproducing short run does not close an old incident.

Preserve CimException evidence and isolated launcher change from
`LOCAL_REPAIR_CLOSEOUT_20261024.md`; actual launcher assembly remains pending.
Production 8001/8020 had no listeners on this turn's bounded check. No accepted
payload, entry, production data, methods, budget or approval was changed.
Restore, permission renewal and exact launch acceptance remain consolidated
user decisions only after an accurate candidate and evidence are ready.
