# Release Verification Rejection And Code-Only Recovery

Updated2026-10-18T11:31Z. This supersedes earlier statements that0f41 was merely
waiting for approval or that no production source changed in this execution.

## Actual Sequence

-11:22:26Z:first tool observation after genuine OWNER reply call_e6b570ea22c64c52975dea4c4fcb8bd0:0;
  exact0f4190e07e36ec96 accepted with all limits. Receipt is preserved.
-11:23:20Z:original identity-aware entry stopped d4f4 for the accepted replacement.
-11:23:35Z:37 approved target files and entry switched; launch requested, not yet healthy.
-11:23:40Z:actual detached launcher exited during RELEASE_VERIFICATION, before
  either new backend/SDK/worker started. No new code was reported as scanning.
- Read-only comparison found exactly one contradictory path: files section binds
  web/dist-unified/unified.html to actual new f7203723857de5caa6e2964f6859bd2a759debbd47bb28150ed40fb96050f27c;
  frontend_files still binds it to old f5efb04e5bbfe16b4897bd7f82de8679a7ccb6240f24d10a51804e0b5556a618.
  The actual original PowerShell entry correctly rejected the mismatch.
-11:26:41Z:verified small archive restored only prior code/config/build/entry,
  removed only newly added exact-hash files, no database opens/writes in recovery.
-11:26:47Z:original d4f4 five-role gate passed, can_launch=true, no business writes.
-11:27:44Z:original entry created d4f4 backend37480/gateway37748.
-11:28:10Z:actual services RUNNING/MAIN_LOOP, session8919c1cd-1acf-499c-b849-daef2396c259.
  Bounded read-only restored-service observation subsequently completed600.062s:
 21samples, same exact candidate/session, all MAIN_LOOP/worker ready, loops11->131,
  heartbeat maximum14.514s, worker age maximum5.380s. Live/page21HTTP200 each;
  unauthenticated current/compact21HTTP401 each, expected protection not failures.
  State-read errors empty. Actual authenticated browser remains unconfirmed, not
  failed login; native computer-use helper unavailable after bounded recovery.

Raw evidence:runtime/work/option_foundation/runtime/lifecycle.20261018T112339076Z.jsonl,
runtime/work/logs/detached.20261018T112336815Z.22220.log, and
release/local-candidate-0f4190e07e36ec96/prelaunch-code-recovery.json.
No database rollback, copy, index deletion, credential change or extra SDK lane.
The startup acceptance is FAIL for0f41 even though its earlier isolated hour
had5393/5393 reads and safety/reliability PASS. Keep both facts.

## Minimal Tool Remedy

Original frozen tools/payloads are preserved. New prepare_checked_candidate.py
updates every duplicate declaration and all built frontend artifacts together.
New apply_checked_delta.py checks cross-section consistency and projected byte
hashes BEFORE stopping the accepted observer. pack_checked_delta.py binds it.
No runtime strategy, source method, AI or UI bytes changed:37/37 projected target
hashes equal0f41. Eight pure section cases pass; actual old manifest is rejected
before stop, corrected manifest passes. Evidence:evidence/release-hash-boundary-20261018.json.

Actual Windows PowerShell5.1.26100.4480, same executable as detached entry, checked
465 projected declarations at11:31:21.2164244Z, all passed. No SDK/production writes.
This is metadata/byte verification, not a substitute for actual guarded startup.

New unaccepted identity:local-candidate-b6cf37cc4955061a.
Payload72d8a036b952b261909ac7f4fe6a84d3a6621dba7626a9e097c6d36e20168371.
Projectionacc282787ae8e46f683d3467248d8afcc7147ba68f1052dbfaca820eda055306.
No old approval is borrowed. New short is running in session2379,
evidence monday-release-short-b6cf-20261018. After its final counters/cleanup,
one matching exact hour, then a concentrated metadata-only scope decision.
d4f4 stays running throughout. No unchanged repeat of the old rejected identity.
Fixed2026-10-23T14:30:22Z deadline and deferred private key remain unchanged.
