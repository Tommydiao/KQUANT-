# D7-W02: Accepted Method Integration And Measured Bottlenecks

This is an execution record, not a replacement plan. Fixed deadline remains 2026-10-23T14:30:22Z (Beijing22:30:22). No T0 reset at midnight or on candidate change.

## Authentic Choice And Runtime Boundary

The direct user response accepted LOCAL_CLOSED_SNAPSHOT_V1, hash `37b7b37759b2ae8a1021f85fa5d9dce3286999a646ce9ff55a8ace17fb4f01b2`. Receipt hash is `5471371579556171685106c018565e755b4e3e118a32dd6d7bfa490458348e95`; effective time is the first tool-observed UTC after the response,2026-10-16T15:24:33Z, not an invented message timestamp. Expiry stays2026-10-23T14:30:22Z. The source proposal is unchanged. `minute-method-binding-20261016.json` proves that only canonical_resolution_method changes in the pending source config.

This choice does not approve launch, strict S0 cross-day reference, contract units/deliverables, orders, new fees or system time changes. The accepted6ac8 service stayed running. Last small observation before this record: `patch-snapshot-20261016T160721Z.json`, both live/page HTTP200, accepted parent hashes unchanged. The snapshot is an observation, not a guarantee of continuous availability.

## Implemented And Exercised

- Real Worker constructor and recovery callback: push-only input no longer short-circuits native NoAdjust recovery; original checkpoint/deadline, generation/CAS and WAIT_INPUT wakeup retained. Isolated synthetic transport produces a full S1 result while missing strict previous-close evidence still leaves S0 INCOMPLETE.
- Canonical resurrection: after a later legal contradiction, repeated resolver invocation could select the same superseded pull again. The before-fix regression failed; the fixed real resolver rejects it and ambiguous equal-time contradictory prices. No OHLC merge or changed method hash.
- Bounded atomic write:25 new decisions formerly opened26 connections (one read,25 writes); now two. Synthetic20-symbol benchmark fresh-call P95 moved0.202814s to0.024852s. Unchanged decisions avoid writes. This is not whole-market latency.
- Indexed lookup:3000 synthetic continuation rows,100 symbol queries. Before:table scan plus temporary sort,total1.622403s,P950.020897s. After:exact session/symbol/time index,total0.105574s,P950.001460s. Result hashes identical. `canonical-index-profile.json` retains both plans/samples.
- Restart safety:the exact OPENING_SOURCE_INDEX_V1 declaration is tied to the new candidate. A real child probe allows only the named exact index; other schema, business-prefix, identity or unaccepted-manifest changes still reject. Source readers never migrate a DB.
- Windows source-file lock:one existing eight-thread regression failed at `lock.open("xb")` with PermissionError. The narrow fix uses nontruncating open and initializes the sentinel after acquiring the byte lock. Five repeated40-writer rounds, timeout/recovery and real ACL-denial behavior pass. Original5-second maximum is not increased.
- Available empty expiry responses end the reference collection job; failed/unknown empty responses do not become NO_MATCHING. Original expiry summary/hash retained; DTE unchanged.

## Test And Assembly Limits

Final related run:199 passed in34.83s, `related-tests.xml`. This follows a separately observed child-import failure when launched from the wrong test cwd, then one real source-lock concurrency failure. The correct cwd is the accepted code root, but modules under test are explicitly loaded from the pending overlay. No test was deleted or weakened. Tool output retains the failures; their old XML paths were reused, so those earlier XML files are not claimed as retained raw artifacts.

Short real-process v3:85.25s,no unexplained errors,enqueue-to-commit five-point P9515.172/12.188/11.735/15.375/16.781s with profiling. v4:120.125s,no errors,P955.469/5.047/6.172/6.672/8.563s without profiling. Cadence and instrumentation differ; this is not a clean end-to-end speedup comparison and both FAIL the2s target. Do not replace those numbers with the shorter CPU subsegment.

The first frozen d46 hour attempt ended at19.984s with initial snapshot readiness failure,27 unexplained HTTP failures and a source-inventory mismatch. It did not last an hour. Its test-only projection environment marker was being cleared by the base configure step; the adapter now preserves that marker and saves both inventories. The initial snapshot failure's policy/cold-start cause is not proven; subsequent attempts retain a bounded actual policy-path/hash diagnostic. No timeout was increased and all isolated children were cleaned up.

Pending final candidate9dc4f06160f48b0f has payloadSHA256 `6d01a0b86da0ace804517c0614c91057d1194abd091425cb58309d387e33fe48`. It contains11 changed/new files, reuses the accepted frontend, and is not deployed/accepted. Final short/hour results will be linked after completion; starting them is not PASS.

## Real Market Accounting Unchanged

Oct16 original-window baseline remains S0 full0/1000 and S1 timely revised full12/1000, two technical events, zero persisted concrete reference contracts, webpage delivery unconfirmed. Those counts are from `audit-20261016T145528Z.json`, not these synthetic tests. Both strategies have zero100-object all-five-point/both-direction completion. Oct16 predatesT0 and does not count toward the three new windows.

No retrospective method acceptance, late EXPIRED shape or synthetic fixture is inserted into the live ledger. Next complete project-calendar window is Oct19. Strict cross-day coverage and real valid clock attachments remain separate requirements; unknown fees/multipliers remain unknown. Nine Python patches, pending config and receipt are isolated from the healthy accepted service.

## Recovery Pointer

Read `RESUME.md`, `blockers.json`, the newest final topology report and its exact frozen candidate record. Do not repeat epoch/login/NTP/method approval. Exact new O-LAUNCH is requested only after final evidence is available. No background coding is promised while this session or app is closed.
