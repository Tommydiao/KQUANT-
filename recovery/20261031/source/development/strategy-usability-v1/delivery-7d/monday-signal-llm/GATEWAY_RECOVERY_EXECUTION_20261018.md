# Gateway recovery follow-up

## Preserved failure

4998 completed3600.469s,5434/5434 background reads successful but three current
HTTP503 RECEIVE timeouts. Assembly/reliability/performance/combined FAIL.
Exact IDs TEST_ONLY-14408-0-3, TEST_ONLY-14408-1-3, TEST_ONLY-14408-2-3.
Crash overlap alone is not proof. Original report/classifier/summary unchanged.

Production remains STOPPED after genuinely accepted b6cf failed the existing
watchlist timestamp guard. No business data rollback, timestamp rewrite or new
data cycle. Original b6cf and0f41 genuine acceptances/failures retained.

## Bounded diagnosis and local replacement

The actual current route is async and reads background memory. A separate actual
Supervisor/Worker/process short with12-second thread/request trace completed
120.438s/errors[]. It did not reproduce RECEIVE timeouts. Early request sampling
showed prompt responses and a selector-idle backend; exact historical cause remains
UNPROVEN, not attributed to SQLite/SDK. The first two diagnostic-only environment
binding failures are preserved as separate failed runs, not production faults.

The prior Gateway creates a new upstream client/connection per snapshot request.
New local transport replacement reuses one lifespan-owned bounded client only for
existing bounded GETs.16 total/8 keepalive connections,5-second keepalive retention;
no completed response cache, automatic retry, increased request budget or thread.
HTTP .75second and outer .75second limit unchanged. Stale/503 remain visible.
CookieJar refuses backend cookies, so users cannot share backend sessions through
the connection pool. Other methods and their existing transport are unchanged.

Seven isolated tests pass, including actual TCP reuse and reopening after peer
close, no cookie sharing, fresh revisions, three-reader single flight, connect/
receive/slow failures, no blind retry, next-read recovery and shutdown cancellation.
These support the local mitigation, not a proven cause for old three failures.

## Exact frozen candidate

Candidate cc97f95a84a01704, payload
a4415d33c869e1bccf44c59218c435aa97cd130e9ef7906e973020832e4c5cff.
Projection SHA25615425f05ca6f036e38ba39a9af4b06477b4f77d2afeefd8bf3eac20379ea6241.
Compared with accepted b6cf, runtime differences are the two narrow restart guards
and Gateway transport module. Strategy, frontend, source methods, fee caps unchanged.
Actual stopped-only deployment dry-run passes, production writes0. No OWNER cc97
acceptance exists. Its small archive is1193327bytes/77entries and locally roundtrip
verified; cloud upload/redownload NOT performed.

Next: complete changed short; if successful, run exactly one matching hour with
unchanged frozen payload/harness. Preserve failures independently. Submit one
accurate launch decision only with final evidence. Supplemental stopped-recovery
tool requires explicit exact hash acceptance; it never kills mismatching old PIDs.
After genuine acceptance original five-role gate/entry and600s real observation.

Fixed deadline2026-10-23T14:30:22Z unchanged. User deferred private OpenAI key;
no retry or new credential request. Real model response/cost remains unverified.
