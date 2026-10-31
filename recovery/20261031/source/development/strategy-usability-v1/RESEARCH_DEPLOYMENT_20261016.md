# Accepted Limited Research Deployment

Candidate: `local-candidate-6ac8a5653d14a392`.
Payload SHA-256: `918d56b36f7565c7d083b37e080d17c23ad5b48e1a0a3766edcf9b80c8d31077`.

The OWNER directly accepted the exact limited-research scope in reply to
`call_633f35e5dd31435c97f88bee9b54ccc2`. The receipt is
`release/local-candidate-6ac8a5653d14a392/owner-shadow-acceptance.json`.
This does not authorize qualified buy alerts, source facts, S1 manual-position
policy, orders, clock changes, or automatic startup.

## Deployment Evidence

- Baseline entry, release, recovery, rollback archive and all 25 payload files
  verified before stopping the old candidate. Post-application 25/25 hashes match.
- Initial Windows PowerShell 5.1 invocation inherited an unsuitable module path
  and failed capability preflight before stopping any service.
- PowerShell 7.6 converted JSON creation timestamps to DateTime objects; the
  original stop script rejected string/object comparison despite equal process
  PID, executable and creation instant. No identity check was bypassed.
- Windows PowerShell 5.1 with its standard process-local module paths passed
  capability checks. The unchanged original entry stopped the old service.
- Only listed code/build files were replaced while stopped. Retired build files
  remain available; no business database was copied, initialized or rolled back.
- Original bounded preflight: can_launch=true; five active database opens,
  zero business writes, zero F-drive reads, no errors. Old positions remain UNKNOWN.
- Detached original entry launched PID 26344 at 12:39:43 UTC. Backend PID 23176
  reached startup and the worker entered PREWARM with a current 111-item scope.
- The observation monitor records HTTP, PID identities, heartbeat and log sizes
  in `release/local-candidate-6ac8a5653d14a392/live-observation.json`.

## Outstanding Checks

Ten-minute observation completed at 12:50:24 UTC: 601.578 seconds, 21 samples,
one unchanged run session, all MAIN_LOOP, maximum heartbeat age 11.957 seconds.
Health and page returned HTTP200 in all 21 samples. Worker loop count reached
598, thread_alive=true, runtime_health=RESPONSIVE, 111 registered items. The
current dual-source clock attachment was VERIFIED_BOUND. Recovery count was zero.
See `release/local-candidate-6ac8a5653d14a392/live-observation-summary.json`.
The user reports successful login, but the inspected in-app tab still shows the
login page after reload. Authenticated Signals/SSE verification remains pending;
All 21 unauthenticated current/compact HTTP401 responses are not transport failures or successful
authenticated query.

Startup recorded one status child PROCESS_DEADLINE around 12:39:56 UTC, with
2225.734ms process time, 1131.006ms query time and last phase IPC. It remains a
real failure; health200 does not erase it. No running source was hot-patched.

## Preserved Limits

The matching 3600.422-second isolated hour passed safe observation assembly, not
performance. Enqueue-to-commit P95 remains 4.016-5.218 seconds. This is not live
market-receive latency or browser delivery latency. Strict source/contract gaps
remain. PREWARM is not NO_TRIGGER, and no natural live signal acceptance is claimed.
