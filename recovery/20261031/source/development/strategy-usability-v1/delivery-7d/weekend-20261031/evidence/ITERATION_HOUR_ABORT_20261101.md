# Isolated hour attempt: FAIL, stopped early

Run: `iteration-frozen-hour-20261101`.

The controller reported 600.031 seconds, not 3600 seconds. Original report and
raw failures are retained. Background accounting: 814 attempts, 643 successes,
171 failures, zero deadline outcomes. Test sources were unchanged during the run.
Final cleanup reported no surviving test children.

The recurring failure was a ValueError in current_cards. A separate read-only
reproduction against the exact TEST_ONLY research database identified
`LIVE_CARD_BOUND_EXCEEDED`; see `iteration-current-before-20261101.json`.
The live range contained repeated input generations. The old selection applied
its 222-row bound before collapsing these into latest checkpoint positions.

At 2026-11-01T10:05:16.9967369Z the operator stopped only test backend PID 13764,
after checking its creation time 2026-11-01T09:57:05Z, Python process identity,
and controller parent PID 12600 whose command named this exact isolated run.
The controller subsequently encountered BrokenPipeError at the next checkpoint
and executed cleanup. This later BrokenPipeError and post-stop connection errors
are consequences of early termination, not the original current_cards cause.
They must not erase pre-stop failures or be relabelled as the original injected
crash contract. The raw report's 135 unexplained HTTP observations remain intact.

No production listener, accepted payload, business database, source method,
fee authorization, system time or SDK connection was changed by this stop.

After test cleanup, the candidate query was changed to select latest committed
positions within its indexed time range before applying current-state predicates.
No index, table, row limit, timeout or thread count was added. The same read-only
probe then returned 99 positions and 3 displayed cards in 0.0556773 seconds;
see `iteration-current-after-20261101.json`. It is a narrow regression result,
not a replacement hour or production acceptance.

The attempt also exposed an acceptance-accounting gap: original progress records
did not carry evaluation identity/state, and first-result timing could refer to
INCOMPLETE. The next candidate adds compact committed evaluation references and
tests first-full timing separately. Historical first-result measurements stay
unchanged and are not retrospectively claimed as first-full measurements.
