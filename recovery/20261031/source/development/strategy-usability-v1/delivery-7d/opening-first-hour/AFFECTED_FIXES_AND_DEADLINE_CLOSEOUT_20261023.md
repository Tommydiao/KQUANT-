# Affected Fixes and Fixed-Deadline Adjudication

Recorded at 2026-10-23T15:48:48Z (23:48:48 Asia/Shanghai).
T0 remains 2026-10-16T14:30:22Z. Deadline remains 2026-10-23T14:30:22Z.
This adjudication is late by 78 minutes 26 seconds. The deadline was not extended.

## Final Decision

Seven-day usable-flow delivery: FAIL. The required reliable live chain and observation-window evidence have not been established. This is not NO_TRIGGER and is not a profitability judgment.
Performance: FAIL. New candidate release: NOT ACCEPTED / NOT DEPLOYED.
Natural qualified signal: NOT VERIFIED. Real LLM capability: NOT VERIFIED; no API calls were made in this turn.
The prior accepted release and genuine receipts remain intact. No new approval is inferred.

## Implemented Local Changes

All changes are confined to this isolated opening-first-hour candidate:

- first_hour_journal.py: reuse one policy read within each bounded registration/advance/ready operation, without cross-operation caching.
- test_first_hour_journal.py: assert one policy read per operation and a fresh read for the next operation.
- first_hour_store.py: fetch selected current-card row IDs directly inside the same read transaction instead of repeating full time/JSON predicates. Original 300ms budget remains.
- first_hour_runtime.py: avoid repeated policy parsing inside checkpoint loops; preserve generation, CAS, original deadlines and cutoff.
- assembly/live_fact_topology.py: bounded TEST_ONLY backend 503 cache-state diagnostics, without credential headers.
- assembly/run_assembly.py, check_r58_p9_browser.cjs, browser_response_evidence.cjs: bind isolated browser evidence code and collect allowlisted error fields, including responses without Content-Length.

No accepted production payload, strategy thresholds, business database or system clock was changed. No production stop/restart was issued. No timeout was expanded.

## Affected Verification

24 affected Python tests passed after the runtime changes. The saved affected-20261023.xml predates those final runtime changes; the later pass is console evidence, not an updated XML artifact. Two inline Node sanitization assertions passed.

Four actual-process short runs completed and cleaned up their children. Evidence directories are under source/evidence/new-machine-20261008:

| Directory | Background successes / attempts | Unattributed browser 503 | Enqueue-to-commit checkpoint P95 range |
| --- | --- | --- | --- |
| first-hour-read-followup-20261023 | 516/516 | 4 | 6.469-14.844s |
| first-hour-read-followup-b-20261023 | 497/497 | 5 | 6.203-15.563s |
| first-hour-read-followup-c-20261023 | 493/493 | 5 | 6.406-12.015s |
| first-hour-read-followup-d-20261023 | 490/490 | 4 | 5.813-13.797s |

These are different candidate/configuration identities, not one pooled stability PASS. Each used real process assembly with explicit TEST_ONLY transport/clock, compressed eleven checkpoints, three pages, revision history and 100 pending-task recovery. They are not real-market windows or matching hours. The final no-profiler control still failed latency targets. Slot11 enqueue time fell from 11.891s in the first run to 0.781s in the last, but this does not establish the receive-to-calculation target.

Latest test identity: b875b58b1973574c6b271f338b4c75550d8c8211cddb0146768a76c6e4ae3005.
Latest browser failures: TEST_ONLY-browser-90, -91, -92, -93. The approximately 765-770ms status/current responses remain unclassified beyond HTTP_FAILURE_REQUIRES_ATTRIBUTION. Backend cold-cache diagnostics do not prove the cause of these four failures. Temporal overlap with restart does not exempt them.

The October22 matching hour remains FAIL: 5436/5440 background success, four browser 503, P95 10.875-36.281s. It does not cover the changed candidate. No new hour was run because the short gate still failed. No release approval is requested for this candidate.

## Actual Service Failure

At 19:05:52 BJT the accepted 198444f784fb3ada service returned health successfully, with verified process identity and heartbeat age 7.374s. This is a point observation, not proof of continuous runtime afterward.

Existing runtime/work/option_foundation/runtime/lifecycle.20261019T134803640Z.jsonl records:

- 2026-10-23T12:33:46.8529287Z: FAILED, MAIN_LOOP, LAUNCHER_ERROR_CimException; hresult -2146233088, script_line 42.
- 2026-10-23T12:33:55.9868957Z: EXITED with the same reason.

services.json records STOPPED, recovery_count 0, no listeners, health_verified false. At approximately 23:46 BJT live health refused connection and no listeners existed on 8001/8020. Windows boot time remains October14 21:15:48; this evidence does not show a new reboot.

The lifecycle exception is established, but its underlying cause is not. There is no evidence here attributing it to the short tests, storage or a user stop. Current post-deadline inspection corroborates a pre-deadline stop record; it is not a substitute for deadline-time live sampling.

## Evidence Limits and Final Counts

This turn did not obtain a complete October23 real-window funnel. Actual expected/full/trigger/reference/page/expiry/system-missing counts remain null pending existing-evidence reconciliation; no synthetic count is substituted. Previously recorded real results remain historical and do not prove three complete windows or the 90-percent target. Old holdings/events/tasks continuity remains UNKNOWN.

No frontend production deployment, natural opportunity, model response, paid usage or cloud backup verification was performed this turn.

## Smallest Replacement Decision

Stop the unchanged patch/hour loop. Proposed narrow replacement boundary: the status/current snapshot publication and read adapter, retaining existing routes, authentication, same five databases, immutable snapshot generation/watermark and original read budgets. Validate error attribution and cold/recovery behavior before another matching hour. Do not replace strategy algorithms or rebuild the project.

Separately isolate the launcher's CIM identity-query failure so a monitoring exception cannot silently terminate observation; require bounded unknown/unsafe handling without killing unrelated processes or weakening launch identity checks. This is a proposed follow-up, not an implemented fix or accepted release.

Any continued real operation must explicitly account for expired time-limited research-method and LLM-budget permissions. No automatic extension, restart or new paid use is authorized by this report. Preserve existing receipts and data. Resume only under the user's next scope decision; the seven-day outcome remains FAIL.
