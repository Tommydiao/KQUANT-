# Rate attribution and queue repair, 2026-10-24

Seven-day FAIL remains unchanged. No production restart, release, permission
renewal, business database change, SDK request or paid model call was made.

## Implemented

- Gateway generates and forwards an upstream request ID. Responses sharing one
  in-flight request retain the same upstream identity. Transport failures keep
  that ID; 429 responses preserve status and Retry-After. No rate-cap increase.
- S0/S1 policy construction is shared within each bounded computation batch;
  policies are freshly read for each batch, not cached across batches.
- Removed repeated policy-file reads while holding the lane condition lock in
  original-checkpoint wakeups. Window deadlines use the same adapter constant
  that produces the policy and schedule: 60 minutes. No deadline extension.
- Existing READY wakeup repair remains. 30 affected tests passed.

## 429 causal evidence

Actual process run:
`source/evidence/new-machine-20261008/first-hour-lockfree-window-20261024`

Browser request 874 and 873 both carry upstream ID
`b13ee6157ce5487d947db4f961b6157a` for one-minute/status.
Browser request 876 and 875 both carry upstream ID
`8f7452cc96314797a57aa0594dd21a81` for opening-trend/current.

Both IDs occur in `TEST_ONLY-rate-guard-17328.jsonl`: actual security middleware,
configured_cap=240, actual_window_count=240, status429, Retry-After1. Thus these
four browser failures are two shared upstream rate-limit rejections, not SQLite
exceptions or backend crash exceptions. They remain failed requests; attribution
does not turn them into successful responses. Additional HTTP poll failures also
remain in the original report (seven unclassified HTTP failures there).

Historical four 429 in first-hour-wakeup-trace-20261024 had no server ID. Their
same endpoint/cap pattern is supported by this reproduction, but exact historical
per-request causality is not retroactively fabricated.

## Old 503 boundary

Earlier first-hour-gateway-provenance-20261024 browser IDs95-98 retained header
evidence UPSTREAM_TIMEOUT / GATEWAY_UPSTREAM / CONNECT. Missing historical
server-side IDs/timing cannot be recreated by a newer test. Neither of this
turn's two runs reproduced a non-isolation browser503. Old four remain open for
exact fault attribution, not excused by mere overlap with a crash.
New Gateway evidence distinguishes health-query CONNECT failures from browser
failures. They must not be combined into one denominator or claimed as old IDs.

## Actual validation

1. first-hour-batch-policy-trace-20261024: 240.188s with profiling; 497/497
   background reads succeeded, browser non-isolation failures empty. Profiling
   has overhead and is not a performance improvement claim. It identified
   repeated policy reads in _wake_original_locked / history callbacks.
2. first-hour-lockfree-window-20261024: 240.110s without profiling; 523/523
   background reads succeeded; all eleven points observed200/200 positions per
   variant, no unexplained omissions;100 pending recovered under original
   deadlines. Original report retains seven HTTP failures and four browser429.
   Last-point enqueue-to-commit P95=11.485s, still FAIL. Last-point enqueue call
   sum=.220s versus .454s in the preceding wakeup-trace run; this narrower
   reduction does not prove end-to-end improvement or meet the2s target.

Both runs completed with unchanged tested sources/frontend and no surviving
test children. Tests use synthetic transport/clock/data in isolated processes;
they are not real market windows or natural Signal evidence. No matching hour
was started because short-test reliability/performance gates still fail.

## Remaining engineering

Current local changes reduce redundant policy I/O but do not solve cumulative
input preparation and queue delay. Next work must reduce repeated preparation
under the same generation/method/clock epoch without stale source reuse, and
reduce redundant page requests under the existing240 cap. Do not raise timeout,
rate limits or worker count merely to hide these failures. Old503 attribution
has an explicit evidence gap; unchanged reruns cannot manufacture missing logs.
Restore, renewal and exact release acceptance remain pending consolidated user
decisions, not inferred from this repair request.
