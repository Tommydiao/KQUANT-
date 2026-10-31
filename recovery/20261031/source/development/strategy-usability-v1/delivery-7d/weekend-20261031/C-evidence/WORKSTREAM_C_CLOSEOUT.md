# Workstream C: Lifecycle and DST Isolation

Date: 2026-10-31. Historical seven-day FAIL is unchanged.

## Scope and Current Baseline

Use the parent's `weekend/evidence/baseline-20261031T141424Z.json` for actual production identity: no production ports/original processes; selected manifests still match accepted 1984. C did not restart, stop, replace or modify the production load, five business databases, permissions, clocks or scheduled tasks. Original October 23 CIM evidence was read once; its cancellation trigger remains UNKNOWN.

Only `opening-first-hour/lifecycle-candidate/**`, the new `weekend-20261031/calendar/**` and this C evidence were written. No runtime/journal/strategy, browser or freeze/harness files were edited.

## Actual Changes

- `lifecycle-candidate/scripts/FoundationLifecycle.ps1`: rejects incomplete process identity; shared identity assertion; unwraps observation errors; treats CIM, CIM job and denied process observation as UNKNOWN/DEGRADED in MAIN_LOOP. All sibling identities are read before any recovery, preventing partial recovery when another sibling is unobservable. Actual exits retain the global maximum of three recoveries and original backoff.
- `lifecycle-candidate/start_kquant_workspace.ps1`: calls the same shared monitor cycle at initial MAIN_LOOP and later cycles. A first-cycle CIM failure no longer bypasses the degradation handler. Listener enumeration swallows only the explicit no-match result, not access/provider failures. No timeout, thread, rate, port or strategy limits were raised.
- `lifecycle-candidate/test-process-isolation.ps1`: actual Windows PowerShell/Core entry, real child/descendant identities, actual startup/listener/health function bodies taken from the candidate AST, real loopback health child and process exit/recovery. It never bypasses the production recovery gate.
- `acceptance-child.ps1` and `acceptance-health.py`: bounded TEST_ONLY fixtures. The latter has no KQUANT, SDK, database or provider imports and binds only a test ephemeral loopback port. Exclude these fixtures from production entry dependencies.
- `calendar/window_calendar.py`: read-only adapter to the existing `first_hour.schedule`, project XNYS calendar and original `exit_times`. Stable UTC position IDs separate strategy version and scope; revision reconciliation retains the fixed denominator and distinguishes missing evidence from proven system loss.
- `calendar/test_window_calendar.py` and `capture_calendar.py`: DST/holiday/early-close/repeated-hour/budget-date/UTC-countdown/manual-exit tests and recorded readiness artifact.

## Lifecycle Evidence

Final evidence: `lifecycle-windows51-03/result.json` and `lifecycle-core76-01/result.json`; exact hashes and verdicts in `C_CLOSEOUT.json`.

The checks exercise:

- The real original `Start-Local-KQUANT.ps1 -HostCheckOnly` and host command capabilities.
- The real candidate `-File` entry rejecting an isolated DataRoot without a recovery gate before credentials, services or databases; failure is preserved under that DataRoot.
- Real parent and descendant ownership; an unrelated test process is not owned and survives owned cleanup.
- Real CIM invalid-namespace exception; explicitly injected access denied and missing executable field. All preserve the live child, record DEGRADED with health false, and permit the next successful observation without recovery.
- A deliberately mismatched creation identity is rejected without stopping the process; cleanup with unavailable identity fails closed.
- An actual exited child plus an unobservable sibling causes no partial recovery.
- Actual child exit retains recovery-exhaustion refusal at count three.
- Actual candidate startup/listener/health functions launch a TEST_ONLY child, detect its real exit, restart it once, and verify a new identity and owned listener; all child processes/listeners are cleaned.

These are lifecycle isolation results, not a successful five-role production start or a Worker/HTTP/SSE matched-hour result. The narrow access-denied injection is not a claim that Windows ACLs were changed. Invalid-namespace CIM failure is not proof of the original October 23 cancellation trigger.

## Calendar and Denominator

Installed project functions and `exchange_calendars:XNYS` produce the following for Monday 2026-11-02:

| Action | America/New_York | Asia/Shanghai |
|---|---|---|
| Prewarm | 08:30 | 21:30 |
| Readiness | 09:25 | 22:25 |
| Open | 09:30 | 22:30 |
| Eleven checkpoints | 09:35 through 10:25, every 5 minutes | 22:35 through 23:25 |
| New-entry cutoff and reconciliation | 10:30 | 23:30 |

There are 111 registered objects, 100 applicable and 11 unresolved. Each variant keeps 2200 applicable direction/checkpoint positions; 242 unresolved-identity positions are separate. Each checkpoint retains its own original 300 seconds, capped by 10:30. The 10:30 closed bar is not a twelfth checkpoint.

The 15 calendar tests cover March and November DST transitions, weekends/Thanksgiving, November 27 early close, both repeated-hour folds, unchanged date budget bucket, UTC countdown, variant/scope key separation and revision deduplication. They also call the existing manual exit function: fixed Beijing 01:30 exit and 01:15 wind-down do not shift with US DST; the existing minimum of bedtime/four hours/close-minus-30 remains authoritative.

No task was registered or persisted. `SCHEDULED_NOT_RUN` here is the existing schedule function's prospective state, not proof of an active automation. The budget date helper is not an acceptance of the AI budget ledger; A owns actual reservations. S1 manual policy remains a separate acceptance.

Official cross-check: [NIST 2026 DST rules](https://www.nist.gov/pml/time-and-frequency-division/popular-links/daylight-saving-time-dst) confirms March 8 and November 1 transitions. [NYSE hours and holidays](https://www.nyse.com/markets/hours-calendars) supports regular 09:30 ET opening and November 27 early close. The installed calendar independently supplies the actual UTC session bounds.

## Parent Integration and Gaps

1. Include the two modified lifecycle production files in the accurate candidate projection/hash set. Do not take the old 1984 acceptance as permission to run them.
2. No import or edit to `first_hour.py` is required for DST; the existing schedule is already timezone-aware. Optional read-only imports for final readiness/reconciliation: `window`, `expected_positions`, `reconcile` from the new `window_calendar` module.
3. Parent still owns current/compact business HTTP, actual Worker initialization, compiled page/SSE, short penetration and final 3600-second assembly. C did not run or claim them.
4. Recovery/method renewals/production AI budget/exact release acceptance remain concentrated user decisions. Neither C isolation results nor the schedule artifact supplies them.

Recovery pointer: `C_CLOSEOUT.json` is the machine-readable handoff. Read its hash list, final two lifecycle results and `calendar-verification.json`. C source files are ready for parent integration; do not change them during a frozen acceptance run without coordinating a new identity.
