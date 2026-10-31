# Status Reliability: Actual Findings And Unpublished Fix

Cutoff: 2026-10-17 11:25 Beijing. This is an execution result, not a new master plan.
T0 remains 2026-10-16T14:30:22Z; deadline remains 2026-10-23T14:30:22Z.

## Actual Runtime And Page

The user directly confirmed `能看到Signals页及研究记录/休市状态` in reply to
`call_65f1d1330a2843cdb3299d8bd44ac2dd`. Recorded in
`user-page-confirmation-20261017.json` as USER_REPORTED visibility. This is not an
instrumented SSE/render-latency measurement or proof of natural Signal delivery.
No password, login reset or browser credential inspection was requested.

Accepted d4f4 remains running, with all twelve checked release-file hashes
matching. Launcher32524/backend13792/gateway31476 retain their original creation
times. At03:25:01Z the worker reached4388loops, MARKET_CLOSED/WAIT_NEXT_CYCLE,
thread_alive/research_ready=true, qualified_alerts/Paper/orders=false. The earlier
600.031s continuous process observation remains valid. Later point checks show
continued progress, not another continuously sampled hour.

Live status reliability is **NOT PASS**. At03:25:02.418385Z the parent denominator
is6579 attempts,5687 successes,892 failures,797 deadlines. Available failure logs
split into873 legacy one_minute:status failures,13 opening_momentum:current and6
opening_momentum:compact failures. Success INFO records were not retained, so this
is the parent counter plus available failure records, not complete per-lane raw
success accounting. Do not present all failures as legacy-only.

Source: `release/local-candidate-d4f4aad4be84d143/runtime-evidence-20261017T032504Z.json`.
No new real opening window occurred this weekend. Future complete/trigger/
reference-contract/page-delivery counts stay null. MARKET_CLOSED is not NO_TRIGGER.

## Findings And Implemented Delta

All seven changed production modules are under `legacy-status-fix/patches`, NOT
the accepted workspace or frozen d4f4 patches. No live database or service was
changed, no SDK connection was created, and no source/policy threshold was relaxed.

| Finding | Implemented development change | Verification boundary |
|---|---|---|
| Legacy worker cold-builds the exchange calendar and repeatedly scans the day's evaluations | Reuse a freshly validated parent calendar context; one metadata scan and bounded payload reads; covering index for the actual columns | Original response equivalence, real status CLI and actual background app path pass in isolation |
| Original isolated hour disabled legacy on_tick by supplying research_store | Explicit isolated minute_status_store enables the real existing background loader; GET remains snapshot-only and authenticated | Actual app/lifespan/CLI regression now covers the path; new full topology hour remains required |
| Existing main database is DELETE mode; actual current/compact fail at universe with SQLITE_BUSY | Explicit startup-only existing-file WAL preparation before workers; no per-GET migration or budget extension | Actual production mode verified read-only; separate-process lock reproduction and mitigation pass on isolated stores |
| Adding an index can break safe restart/rollback checks | Exact MINUTE_STATUS_METADATA_INDEX_V1 extension alongside the retained research-index contract | Actual five-role restart probe; wrong role/schema/undeclared index/epoch boundary fail closed |

The observed main-store SELECT joins114 membership rows which deduplicate into the
existing111 universe; it does not redefine the111 denominator. The main store was
read-only-probed five times at03:21:23Z: DELETE/normal, each successful when not
contended. Fifteen captured failure-detail records identify DATABASE_LOCKED at
phase universe. The actual lock-holding writer is **UNKNOWN**. DELETE is a proven
runtime configuration difference and a plausible mechanism, not retrospective
identification of the specific writer or proof every failure shares one cause.

The startup helper opens mode=rw, never creates a missing store, changes only
journal mode, closes its connection, and fails on contention. In the isolated
cross-process test, an exclusive writer prevents the original universe reader in
DELETE; WAL allows that same reader to see the committed111 objects. Business rows
and scope hash remain unchanged. This mitigation is not deployed.

## Performance And Preserved Failures

Actual read-only revised CLI against the unchanged live minute database failed
5/5 without the covering index. A rowid-order experiment succeeded4/5 but still
failed cold; it is retained as failure evidence, not chosen as a claimed fix.

A separate production-shaped TEST_ONLY fixture has75900 evaluation rows and111
registered objects. Through the actual status subprocess, the no-index attempt
failed its existing SQL budget. After the exact index,5/5 succeeded with whole
loader times0.551-0.587s, using the covering index. Business-row digest before/after
matches. The fixture is synthetic, not a copy of active business data, and is NOT
real-market or live-version performance proof. Timeouts remain unchanged.

The accepted d4f4 hour's enqueue-to-result P95 values6.657/7.844/8.688/8.532/10.719s
remain **FAIL** against2s. Neither this isolated query improvement nor fast HTTP
replaces that result. Receive-to-compute and natural qualification-to-page P95
remain unmeasured. Do not repeat an unchanged hour excluding the legacy lane.

## Evidence And Remaining Work

Immutable delta/source hashes and evidence index:
`legacy-status-fix/delta-review-20261017T032542Z.json`, SHA256
`e1efbae316f8d57b7d41168776bcd245ec0182aff0b831bae63d573c2eb0b16a`.
It records the exact seven-file development delta, not a frozen release identity.

Remaining READY work is to include the legacy lane and representative history in
the existing independent-process harness, profile remaining queue delay, freeze
the final small delta, and run its matching short/full hour. The new minute index
and startup WAL behavior must appear in the consolidated exact O-LAUNCH difference.
Current d4f4 is not authorized for these new files. No new approval is requested
until the exact candidate and evidence are ready. Do not drop an index, restore an
old business database, or use old acceptance to force an incompatible rollback.

The strict S0 source facts, concrete-contract evidence and real opening delivery
remain independently pending. S1 stays independent of the previous-close gate.
No new strategy, fee, SDK owner, database, login or data-cycle approval is involved.
Preferred real windows remainOct19/20/21, Oct22backup; fixed deadline is unchanged.

## Test Appendix

Final affected regression:114 passed,2 skipped,1 existing Starlette deprecation
warning (`tests-related-wal-20261017.xml`). The skips require an explicitly provided
retained-store profile root; they are not passes. Earlier failures and corrected
reports remain in the delta directory. Separate40-test direct run covers original
response equivalence, real background read, exact index restart and cross-process
WAL behavior. Counts are supporting evidence, not delivery completion.

All foreground tests/probes completed. Only the accepted services remain running.
No new full-hour process is running. This pointer does not schedule background
coding; the existing heartbeat is a bounded observer, not a developer loop.
