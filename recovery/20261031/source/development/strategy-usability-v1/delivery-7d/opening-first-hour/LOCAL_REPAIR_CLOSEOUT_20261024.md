# Local Repair Execution, October 24

Seven-day delivery remains FAIL. T0 and the October23 22:30:22 Beijing deadline are unchanged. The user authorized continued isolated engineering, not renewed methods, paid use, production restart or release.

## Established Stop Path

Windows WMI event5858, record67401, at2026-10-23T12:33:46.7924630Z records clientPID34668 querying Win32_Process PID24520, result0x80041032. See CIM_EVENT_20261023_SANITIZED.json.
The matching lifecycle FAILED event is at12:33:46.8529287Z, MAIN_LOOP, FoundationLifecycle.ps1 line42. That line is the ancestry/ownership Get-CimInstance call. Its terminating exception escaped heartbeat verification into the launcher outer catch/finally, which invoked owned-service cleanup. The terminal manifest records STOPPED.

Microsoft defines this result as WBEM_E_CALL_CANCELLED:
https://learn.microsoft.com/en-us/troubleshoot/windows-client/system-management-components/wmi-activity-event-5858-logged-with-resultcode-0x80041032
The record does not establish why the query was cancelled. The configured two-second timeout alone does not prove a timeout cause. Nearby service events concern another application and are not attributed to KQUANT. No WMI repair, system restart or storage repair was performed.

## Implemented Candidate Changes

1. lifecycle-candidate/start_kquant_workspace.ps1 and scripts/FoundationLifecycle.ps1: isolate CIM monitoring errors in MAIN_LOOP. Publish DEGRADED/PROCESS_OBSERVATION_UNAVAILABLE, health false, without treating unknown identity as process exit or starting recovery. Mark actual recovery separately so recovery, startup, non-CIM failures and identity mismatches still propagate. Original startup and cleanup ownership checks remain strict.
2. published_status_snapshot.py plus first_hour_http_snapshots.py: publish one coherent value/version reference after collection. Memory readers no longer contend on the refresh lock. Wrong session, missing value, invalidation, TTL expiry and failed refresh remain unavailable/stale. Returned values are detached copies; original timestamps/deadlines are never renewed.
3. gateway_candidate.py: attach allowlisted upstream error code/origin/stage and generated request ID to error response headers. This makes provenance available even when browser body retrieval fails. No retry, timeout increase, auth bypass or successful empty response.
4. assembly/bootstrap.py and browser_response_evidence.cjs: explicitly load isolated adapters and record header provenance plus body-read outcome.

Accepted workspace files were not edited. Both original launcher/lifecycle contents were compared again with their turn-start readings and were unchanged. The production entry still references198444f784fb3ada. These are development files, not an accepted release bundle.

## Tests and Actual Process Runs

affected-20261024.xml:28 tests passed. PowerShell test-monitor.ps1 passes a simulated CIM failure through the actual ownership-query function and degradation handler, checks non-CIM/recovery propagation and parses the candidate launcher. This is not a full candidate PowerShell cold-start or ten-minute live acceptance.

Both short runs used independent actual backend/Gateway processes and the real Worker/Supervisor construction, explicit TEST_ONLY sources, an accelerated eleven-point clock, three compiled pages and100pending recovery. Neither used live SDK or a real market window. Both ended and reaped children. Sources were unchanged during each run.

Evidence under source/evidence/new-machine-20261008:

| Run | Background child-query attempts/success | Browser errors | Enqueue-to-commit P95 |
| --- | --- | --- | --- |
| first-hour-published-snapshot-20261024 | 537/537 | 4x503,2x429 | 5.703-11.266s |
| first-hour-gateway-provenance-20261024 | 534/534 | 4x503 | 5.312-12.266s |

These query counts come from legacy_included_transport_accounting, not browser request counts. The transport files use a status_query_attempt prefix and must be parsed with the existing audit parser, not as bare JSON lines.

The first run missed AI CALL/PUT at checkpoint2. Its durable row later expired with DATA_INCOMPLETE_AT_ORIGINAL_DEADLINE, generation1/completed0. Preserve this failure: no causal claim that the new cache caused it. The second run recorded all expected positions at all11points, but does not erase the first run.

Latest HTTP totals are555successes/564attempts, including9backend-crash/recovery errors matching the harness contract. Its causal_attribution_proven fields remain false; contract matching must not be reported as complete causal proof.

Latest four browser failures, request IDs95/96/97/98, now independently expose UPSTREAM_TIMEOUT, GATEWAY_UPSTREAM, CONNECT and generated server IDs. All are near the deliberate backend crash, but the browser-to-fault attribution is not yet closed. Keep the four failures; do not retrospectively relabel previous runs. Body retrieval still reports UNAVAILABLE_OR_TIMEOUT.

Latest checkpoint P95s in seconds:
5.563,5.312,6.343,6.250,7.360,7.531,8.797,9.172,10.094,10.562,12.266.
These are enqueue-to-commit, not receive-to-calculation. Performance and overall acceptance remain FAIL. No unchanged expensive hour was repeated.

## Remaining Engineering

- Close browser request/fault attribution using the new server identifiers; do not suppress failures by temporal overlap.
- Diagnose the first-run AI pending loss and prove durable re-admission under unchanged fingerprints and concurrent generations.
- Reduce computation/input-preparation queue latency. EXPLAIN confirms current cards already use the expression index trend_current_time; minute reads use one_minute_bars_lookup with a temporary received_at sort. No evidence justifies adding another generic index or increasing timeouts.
- The snapshot adapter removes the reproduced lock-contention failure mode, but the short tests do not establish elimination of historical hourly read failures.
- Run the affected actual PowerShell launcher assembly and then a matching hour only after short-gate failures are resolved.

At final inspection no listeners existed on8001/8020/8193/8194. Production remains stopped; this turn did not stop or restart it. No business data was copied/overwritten, no F drive read, no credentials/API calls, no paid LLM use, no approval or permission extension.
When ready, submit one exact consolidated recovery/expiry/release decision. Do not borrow prior acceptance or change the seven-day FAIL conclusion.
