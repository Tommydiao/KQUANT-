# Request Coalescing and Queue Short Tests - 2026-10-24

## Decision

Seven-day delivery remains FAIL. No restoration, permission renewal, production
write, model request, or release was performed. The accepted payload was not edited.
The isolated candidate is NOT ready for the matching hour or launch acceptance.

## Implemented

- Added web/src/unified/snapshotRefreshPolicy.ts and an isolated
  useOperationalResource.ts overlay. Published current/compact resources ignore
  generic operations progress refreshes; actual snapshot-ready, reconnect,
  manual refresh, visibility refresh, and disconnected fallback remain enabled.
  No rate limit, timeout, or retry budget was increased.
- Built both existing frontends. Route-policy Node checks passed.
- Reused one diagnostic history snapshot per bounded computation batch rather
  than repeatedly scanning the history cache for each result. This does not
  cache price/source qualification.
- Experimental single canonical-decision producer: admission produces durable
  decisions; computation reads them and validates native inputs before CAS.
  Added a regression confirming compute does not call the producer again.
  This change is NOT accepted as equivalent on the basis of unit tests alone.
- 31 affected pytest tests passed before the second topology short run.

## Evidence

Evidence directories are under source/evidence/new-machine-20261008/.

| Run | Background reads | Non-isolation browser failures | Last-point queue P95 |
| --- | --- | --- | --- |
| first-hour-lockfree-window-20261024 (prior) | 523/523 | 4 HTTP429 | 11.485s |
| first-hour-snapshot-events-20261024 | 523/523 | 0 | 11.187s |
| first-hour-single-producer-20261024 | 488/488 | 0 | 9.766s |

The first new run reduced combined current/status browser responses from637 to345
(approximately46%). These are separate short-run observations, not a guarantee
against every future overload. The second run lasted240.157seconds, reported no
harness errors, unchanged tested source/frontend hashes, and no surviving test
children. Both runs use synthetic input/clock/transport; they are not live-market
or natural-signal evidence. Original timeout and rate thresholds are unchanged.

The prior four429 responses were correlated to two upstream request IDs and
actual ApiSecurityMiddleware cap240 rejections, with Retry-After preserved.
Removing duplicate refresh paths addresses that demonstrated load source.
Historical four503 remain classified CONNECT timeouts; exact historical causal
attribution is not manufactured from later successful runs or injection overlap.

## Remaining Functional and Performance Failure

All eleven checkpoints contain200 observed applicable direction positions per
variant, but observation is not completeness. In the single-producer run, point1
has S0 complete192/200 and S1 complete190/200. Final read-only inspection of the
isolated research DB confirms CYN/DGP/DLR/DUK retain PRICE_REFERENCE_UNVERIFIED
for S0 and identity/currency/native-price-basis blockers for S1. AAPL adds two S1
native-price-basis blockers. These are not canonical-decision error labels.
The precise source-publication/wakeup interleaving still requires reproduction;
do not assert that the producer optimization is the cause or that it is harmless.
Subsequent points retain the injected AAPL conflict and all denominators.

Last-point queue P95 improved between these particular runs but remains far above
2seconds. This is enqueue-to-commit, not market-receipt-to-compute latency.
Performance and observation_assembly_pass are false in the second report.
No unchanged costly hour was started, and no failure was waived.

## Resume at the Smallest Remaining Defect

1. Reproduce first-point source publication against an in-flight admission and
   WAIT_INPUT registration; assert every original slot is re-admitted on the
   new source generation before its unchanged deadline. Use real lane init/run.
2. Compare the source fingerprint captured by admission with the rebuilt compute
   reference; avoid repeated preparation or stale-reference readmission loops.
   Preserve current native-minute validation, conflicts, generations and CAS.
3. Profile bounded source/reference preparation separately from queue wait,
   calculation and commit; do not enlarge batch, timeout or rate limits to pass.
4. Run affected tests and a new short topology only after a concrete change.
   A matching3600second run remains gated on the short-run failures above.
5. Any restoration, expired permission renewal, or precise release identity must
   be submitted together for genuine user acceptance. Do not borrow old approval.

Raw report and source hashes: each run's topology_report.json and candidate_manifest.json.
Browser request evidence: browser-events.jsonl and browser-report.json.
This closeout does not supersede historical failures or the fixed deadline.
