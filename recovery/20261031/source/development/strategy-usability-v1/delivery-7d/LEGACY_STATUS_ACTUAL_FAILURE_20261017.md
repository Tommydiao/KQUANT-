# Actual Post-Launch Status Failure

Observed after exact d4f4 release, beginning2026-10-17T02:10:15Z. This is real
production evidence, not a fault injection. The accepted payload is not hot-edited.

## What Is Proven

The new service remains RUNNING with its sole launcher32524/backend13792/gateway31476
and advancing MARKET_CLOSED worker. Its live health/page endpoints respond200.
Public unauthenticated current/compact requests return401 as expected; they do not
prove an authenticated user's page state or a status-query success.

Actual stderr records repeated one_minute:status CHILD_ERROR/PROCESS_DEADLINE.
At02:16:59Z parent counters were598 attempts,519 successes,79 failures,61 deadlines.
Only79 failed attempt records are present in INFO-suppressed logs. Therefore the
raw per-attempt dataset is incomplete, even though the parent process supplies
the aggregate denominator. Do not claim all successes have per-lane raw proof.

`legacy-status-probe-20261017.json` is one bounded standalone read-only call to
the installed status_worker, with the exact five-role environment and real
stores. It preserves a1.4s stack in exchange_calendars/pandas calendar construction,
then a QUERY_BUDGET_EXCEEDED result. No credentials, SDK or database write.

`legacy-status-components-20261017.json` instruments the same production functions
without changing their inputs or SQL deadlines. Calendar history selection took
1.016s. After entering the original one-second read budget, MAX(bar_end)/MAX(created_at)
and latest-bar filtering consumed the remainder. The final query at
options_one_minute.py:441 was interrupted by the original progress handler.
This proves budget exhaustion, NOT SQLITE_BUSY, corruption or a supplier fault.
The standalone diagnostic has a separate outer process bound; production budgets
have not been enlarged.

## Why The Matched Hour Did Not Detect It

dashboard/app.py constructs the legacy background on_tick only when
research_store is None. The isolated topology supplies an explicit research_store
and therefore skips this old lane. Its4720-query success still applies to the
covered assembly, but does not cover this production-only background activity.
This is an acceptance coverage gap, not permission to hide the failures.

## Restricted Follow-Through

Preserve the live accepted payload and exact hashes. The next narrow development
delta should make the original legacy status path bounded on actual-volume data
and include that lane in the isolated topology, without waiting for a real market
window, extending timeouts, adding workers, hiding counters or deleting legacy
history. Profile calendar setup separately from SQL; a single stack sample is not
proof that calendar alone causes the whole failure.

This issue does not justify stopping raw collection or bypassing research source
requirements. Current safe observation remains available, but actual overall
status reliability is NOT passed. No automatic rollback: unchanged6ac preflight
cannot accept the declared new additive index. Do not drop the index or overwrite
business data to force a rollback.
