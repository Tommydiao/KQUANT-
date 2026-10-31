# Writer Recovery And Matched-Hour Closeout

Status: MATCHED_OBSERVATION_HOUR_PASSED, PERFORMANCE_FAILED, NOT RELEASED. Client date: 2026-10-16, Asia/Shanghai.

## Changes Implemented

The accepted 4ae observation workspace and active five databases were not changed. Development remains in the existing strategy-usability overlay. No additional market SDK connection was opened.

1. Result canonical JSON and detached transaction inputs are now prepared before acquiring the research writer lock. The existing CAS generation check and original atomic result/job transaction remain in force. Existing callers can still pass ordinary rows.
2. The price-fact rebind path previously allowed a shared-writer timeout to escape the owner loop. It now retains captured quotes, reports WAIT_PERSIST, and retries without another provider request. Retries have a one-second minimum spacing and a three-attempt bound per session/source identity. Exhaustion is explicit, not silent success; changed source identity permits another bounded cycle.
3. Added regression cases for immutable prepared result inputs, busy-then-recovered facts, no additional provider fetch, and bounded exhaustion/source-change rearming. All 60 focused tests passed. An initial test incorrectly named the worker class; that test error was fixed, not excluded.

No timeout, lock budget, trading threshold, signal deadline, source requirement, or thread count was increased. S0 is unchanged. Missing sources are still missing. The fixes prevent a known exception escape and move serialization out of the lock; they do not establish that all contention or total latency is solved.

## Evidence And Causal Limits

Prior profiled short runs failed at `_price_fact_quotes -> _journal_guard` with CHECKPOINT_INTERNAL_WRITER_BUSY. This is an application writer mutex timeout, not evidence of disk corruption or a proven SQLite engine failure. The profiler, compressed cadence, simultaneous source assembly, and result writes affected those runs. Their failures remain in the original reports.

The new short actual multiprocess exercise completed 60.062 seconds, all five checkpoints and recovery, with no unexplained HTTP errors. Enqueue-to-commit P95 was approximately 3.813, 4.171, 3.921, 5.312 and 5.469 seconds. It is not a full-hour result or a 2-second pass.

The matching hour uses unchanged source/build, actual Supervisor and Worker construction, independent backend/Gateway, existing five-role assembly, three browser pages, revisions, missing source/time evidence, slow inputs, writes, and pending-job crash recovery. Market transport and clock fixtures are explicitly TEST_ONLY. The historical test session is 2026-10-15; this is not the current day's market observation.

Hour report: `../../evidence/new-machine-20261008/strategy-usability-hour-20261016-v1/topology_report.json`.

## Final Hour Result

- Actual duration 3600.422 seconds; original 300-second checkpoint cadence; source and frontend unchanged throughout.
- Five checkpoints each covered 222 registered directions: 200 evaluated and 22 identity exclusions; no unexplained missing direction.
- Enqueue-to-commit P95: 4.016, 5.218, 4.360, 4.141, 4.406 seconds. Performance remains FAIL. These values are not market-receipt-to-calculation or browser-delivery latency.
- Four monitored endpoints each had 2079 requests, 8316 total. Memory-live: 2079 HTTP 200. Compact, current and stock-live each: 2076 HTTP 200 and 3 HTTP 503.
- All nine 503 responses matched the preregistered crash contract's endpoint/error/PID/window constraints. They are EXPECTED_INJECTED_FAILURE, not a claim that all requests succeeded. The report retains causal_attribution_proven=false; this contract classification is not independent causal proof. No other unexplained HTTP failures were reported.
- HTTP P95: memory-live 0.078s, compact 0.109s, current 0.156s, stock-live 0.109s. HTTP speed does not establish signal-delivery performance.
- Pending calculation jobs: 100 before crash, 100 restored; original deadlines preserved. No test child processes remained. No observed event-loop exceptions.
- Actual isolated manual handlers: login/entry/partial exit HTTP 200, idempotent repeats, changed operation key rejected with 400, expired/logged-out sessions rejected with 401, remaining quantity retained after relogin. This is a synthetic contract, not a real trade or production-user login.
- Compiled browser checks retained explicit old-position UNKNOWN warnings; deliberately unmounted legacy endpoints remained separately classified. Natural signal delivery remains NOT_ACCEPTED.
- observation_assembly_pass=true; performance_pass=false; full_acceptance=false; live_market_acceptance=false. The production_restored=false field does not mean a failed production restoration: this run never modified production.

## Publication Preparation

Unaccepted projected candidate: `local-candidate-6ac8a5653d14a392`.

- Release manifest SHA-256: `20be71878ccb8c4df4919978bf46035fdaaabd8189ab723206b65eebec61aaa8`.
- Recovery manifest SHA-256: `25e47d9e9f38549d94e5f0a7dc509c35125e2aa05233cd980bc4a38149310af0`.
- Deployment projection SHA-256: `af579d27c896211e2dba1c177b9f0dca2fa96bede5983bac8ad791d1dfeb129f`.

The projection binds 25 replacement/addition files and the unchanged accepted baseline. All 337 projected runtime/frontend file hashes were verified against their actual base or overlay bytes. It is stored under `release/local-candidate-6ac8a5653d14a392`; no entry was selected, no live file was replaced, and no OWNER record was created.

The proposal deliberately reuses the existing data-scope acceptance and five-role identities. It does not approve strict source facts, S0/S1 qualified buying claims, orders, Paper, system time changes, or automatic startup. The original entry remains selected until a genuine exact decision and controlled deployment.

Candidate payload hash using the existing recovery gate: `918d56b36f7565c7d083b37e080d17c23ad5b48e1a0a3766edcf9b80c8d31077`.

Changed-file and rollback archive: 1,082,141 bytes, 47 members; SHA-256 `0ff7682db527f4eea1397cda36c43d2f4f5b984a7ea96267d7a215eb985c0964`. Every member was read back and hashed. This is archive verification, not a performed production rollback. No database or credentials were included.

Remaining engineering limitation: shared-writer throughput and end-to-end calculation latency are not fully solved. Source hashing, admission/queue work and commits still contribute. A future optimization must preserve source-change detection and CAS and receive its own matched validation; the current candidate may only be considered for limited observation with this limitation explicit.

## Deployment Boundary

After a genuine exact acceptance only: verify the unchanged base entry and delta hashes, stop through the original identity-checked entry, retain a changed-file-only rollback payload, apply the listed replacements while stopped, recheck hashes and five-role preflight, bind the authentic acceptance, select the proposed entry, and start through the original entry. Preserve all business and approval data. Do not copy or roll back any database. An unexpected base drift or failed preflight stops deployment.

Safety assembly, performance, actual market delivery, and natural signals are separate verdicts. No successful short run, theoretical option cost, or synthetic positive event is a real-market acceptance.
