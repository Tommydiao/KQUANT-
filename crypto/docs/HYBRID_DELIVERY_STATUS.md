# Hybrid V1.2 Delivery Status

2026-09-06. Current task: autonomous local engineering continuation, not Live activation.
Actual branch `codex/crypto-evidence-testnet-v1`, HEAD `baac8d1`.

## Latest Integrated Checkpoint

### M4 Scope Revalidation

`outputs/hybrid_delivery/t21_scope_audit_20260906_01/current_evidence/evidence.json`
revalidates both the process driver and numerical child's source hashes. The
registered probability family is BASE-cost daily-loss only, four comparisons,
family alpha 0.05, 5,000 paths, 72 bars and 12-bar blocks over the fixed exposed
30-day input. Family alpha is a numerical confidence budget, NOT a 5% trading
risk admission limit. Thirteen affected checks pass; no simulation was rerun.

G4 remains ungranted: full semantic/numerical acceptance and the formal risk
event/admission policy are not established by this prerequisite audit. Actual
authenticated venue protection belongs to downstream G8 and is no longer listed
as a prerequisite blocking local M4 work. Production protection is still not
claimed by independent synthetic callbacks. No sizing/selection consumer was
enabled and no existing risk threshold was relaxed.

### Continuous Observer Increment

Read-only live snapshot audit is now implemented in
`scripts/audit_hybrid_continuous_observer.py`. It copies the independent SQLite
ledger with a 20-second backup deadline, then verifies event/label hashes,
checkpoint/latest-label identity, fill/label separation, entry chronology and
mature BASE R. It does not connect to accounts or change the source writer.
`outputs/hybrid_delivery/continuous_audit_20260906_01/live_snapshot/report.json`
passed local ledger checks for 683 committed quotes, two closed batches and
two commit observations; zero opportunities/labels. Eleven affected tests pass.
These new modules are not claimed to be covered by the earlier 938-test run.

Coverage is explicitly descriptive within the committed event envelope. The
current run's exact preregistered monotonic SLO origin is not bound, so this
audit does not manufacture it or grant G3. Raw rejected quotes remain separate
from committed ledger counts. Following the snapshot, PID 41956 was again
verified live, and its heartbeat had advanced to 769 qualified quotes and four
clock segments. The requested 24 hours had not yet elapsed.

New independent CLI: `scripts/run_hybrid_continuous_observer.py`. It reuses
the unchanged A policy, ObservationStore and receiver-clock contract. Clock
renewal happens before expiry, rejects conflicting intervals and never changes
native event times or freshness. Raw quotes/closed bars, source copies, hashes,
clock segments and checkpoints live in the new run directory. No model or order
consumer is loaded. Maximum run storage and minimum remaining disk are 2GiB.

`continuous_smoke_20260906_01` completed two clock segments, 335 qualified quotes
and 630 receipt-order rejects, with no opportunity/label. It exposed a bootstrap
handoff gap: warmup last close 1788663300, first streamed bar start 1788663600.
The original kernel correctly emitted DATA_GAP_RESET. Keep this run unchanged.

The new entry point now retries warmup only BEFORE observation if a close
boundary was crossed. Another boundary at WebSocket handoff fails closed.
After start it never backfills signals. Closed messages wait until their actual
receipt upper bounds precede the current lower bound, within the unchanged
30-second deadline. `continuous_smoke_20260906_02` completed 367.29 elapsed
seconds including cleanup, with two clock segments, 121 qualified quotes and
837 receipt-order rejects. One complete batch yielded BTC RANGE, ETH UP_TREND,
SOL TRANSITION, all without entry triggers and without DATA_GAP_RESET.
Input availability upper bound 1788664200.5986357 preceded processing lower
bound 1788664200.7790034; commit time is independently stored.

Control CLI: `scripts/control_hybrid_observer.py status|stop --run <relative run>`.
Status is explicitly historical heartbeat, not proof of a live process. Stop
only creates that run's marker, never kills a PID. Failure ends the run and
preserves censoring; recovery currently requires a new directory, not automatic
reconnection of the same ledger. Short tests do not establish 24/72h availability.

Checkpoint 11: code suites passed, but the frozen baseline audit rejected an
addition to the old M2 report. That addition was withdrawn and moved here;
the failed checkpoint is retained, never relabeled as all-green.
The corrected baseline audit then exited 0. Composite receipt
`outputs/hybrid_delivery/continuous_observer_20260906_01/receipt.json` binds the
938 passed / 8 skipped / 27 subtests regression and repaired baseline to current
source hashes. The stop drill `continuous_stop_smoke_20260906_02` actually exited
0 with STOPPED/owner_stop after 30.07 seconds, without terminating other PIDs.

A new 24-hour public observer was launched in a hidden process, PID 41956,
at local UTC 2026-09-06T03:13:47.598Z; OS process existence and fresh heartbeat
were subsequently checked. Output: `outputs/hybrid_regime_v1/continuous_24h_20260906_01`.
Initial observation consumed a real closed batch and 89 qualified quotes, with
zero opportunities or labels. These initial counts are not a completion claim;
read current status and verify the actual process. It runs only while this host
is available and terminates on failure or its resource/time limit. Existing
two-hour scheduler `kquant` was confirmed ACTIVE and was not duplicated.

`outputs/hybrid_delivery/checkpoint_20260906_10/checkpoint.json` records
929 passed, 8 skipped, 27 subtests in the full Crypto regression. Isolated math,
diff check and protected baseline audit exited 0; captured source hashes were
unchanged during the tests. No frontend code was changed in this increment.
The combined partial receipt is registered in the existing delivery database at
`outputs/hybrid_delivery/partial_checkpoint_20260906_10/partial.json`.

The receipt references the 5,000-path independent process benchmark (480
synthetic protection parity checks), the bounded 80-qualified-quote observation
(zero new opportunities/fills/labels), MC prerequisite audit and current public
exchange-rule archive. These remain separate evidence scopes, not G3/G4/G8 PASS.
The public rule refresh indexed BTC/ETH/SOL using local receipt milliseconds;
it neither supplies native quote event times nor verifies account permissions.

Current readiness is NOT_READY, with G2-G9 missing. No capital, account or
authorization expiry has been supplied to the readiness runner. Model remains
DEV_ONLY / ABSTAIN, performance remains UNPROVEN, and live remains disabled.
Remaining work includes continuous observation, formal mathematical acceptance,
integration and authorized account/notification evidence; this checkpoint does
not claim that all remaining engineering is finished.

## Verified Intake

- Imported only seven new plan/docs files; original archive is preserved in
  `outputs/hybrid_delivery/bundle_v1_2_20260906`. Bundle validator passed 34 tasks,
  12 gates and hashes. This is not an application or trading PASS.
- Current intake `outputs/hybrid_delivery/intake_20260906_01/audit.json` verifies
  existing outputs, protected source hashes, 27 A mature / 23 unfilled labels,
  and identical four-file tracked diff. B185 is not merged; holdout unread.
- Old 24h collector reported `completed`, ending 2026-09-05 16:14:50 UTC.
  It was not stopped/restarted. Services and candidate process remain owned by
  the original runtime. Do not restart them as a recovery shortcut.
- Old model remains DEV_ONLY / ABSTAIN. No mathematical selection, sizing or
  live switch was changed.

## Execution State

Authoritative progress: `work/hybrid_delivery/delivery.sqlite3`.
`state.json` and `events.jsonl` are recoverable progress projections, never
financial authorization. `run-ready` verifies completed task receipts and
selects next code work; the Codex session implements code, not a hidden shell executor.

Initial evidence dispatch completed T00/T01/T02/T03/T10/T11/T13. T12 requires
72h observation and a natural full label lifecycle; T17 requires matching quote
labels. These waits do not block T14/T18/T20/T30 engineering.

Final local checkpoint `outputs/hybrid_delivery/accepted_checkpoint_20260906_01`
records 12 scoped VERIFIED tasks, 4 READY, 2 WAIT_DATA, 1 BLOCKED_CONTRACT,
5 WAIT_OWNER and 10 TODO. T14/T15 are diagnostic/DEV artifact deliveries, not
G2 acceptance; T20 is path/risk-input engineering, not G4. T30/T31 are Mock
engineering. All worker ownership leases were explicitly released after completion.
Partial T32/T33/T34 delivery is recorded in `partial_work.json`, not promoted to
full task completion. Current next task is T21; alternative runnable tasks are
T32, T34 and T40.

- T14 posterior diagnostics: real saved posterior reviewed, no refit. Tree-step
  saturation 341/1500 in chain 3. Support/output calibration remains unvalidated.
- T15 fresh artifact availability registration:
  `outputs/hybrid_delivery/dev_registration_20260906_01/availability.json`.
  It proves availability now, never rewrites original timestamps or enables predictions.
- T18 prospective timing registry implemented/tested, protocol registered;
  no D0 or evaluation block opened. 10R and formal calibration policy unresolved.
- T20 synchronized MC inputs ran against 8,641 aligned three-asset bar batches
  from the last 30 authorized DEV days. 32 common paths x 72 bars, fixed seed,
  reproduced exactly. This is actual exposed historical input engineering,
  NOT a 5,000-path risk acceptance, current-portfolio valuation or probability PASS.
  Evidence: `outputs/hybrid_delivery/mc_history_20260906_02/report.json`.
- T30/T31 Mock broker/outbox and bounded T32/T33 inventory protection are runnable.
  The three mock suites passed 62 tests. Partial fills, cancellation races,
  UNKNOWN query-before-retry, restart reconciliation, dust and protection-failure
  admission freeze are covered. Native venue protection, authenticated streams
  and actual account reconciliation remain unimplemented/unverified; G8 closed.
  Evidence: `outputs/hybrid_delivery/mock_execution_20260906/protection_v1/README.md`.
- Prospective timing and SLO code have fixed time denominators and immutable
  windows; message acceptance percentages are not uptime. Registered experiment
  D0 remains null. No formal evaluation interval was opened or selected by results.
- Environment/endpoint reference validation rejects production and mismatched
  Testnet origins before secret access. It is a local contract test, not evidence
  of account connectivity or permission. No real order endpoint was invoked.

Latest new quote segment `outputs/hybrid_regime_v1/clock_segment_20260906_01`:
116 accepted / 763 receipt-order-uncertain rejected; one closed batch; zero
opportunities/fills/labels. Ended normally. No 72h availability claim.

## Automatic Continuation

The existing Codex heartbeat `kquant` is reused, ACTIVE, every two hours, same
thread. No duplicate task or Windows scheduler installed. Requires the Codex host
to be available; this is not a 24/7 market collector. Notifications only on
meaningful progress, failure or necessary approval. Per-session cap 60 minutes,
new paid budget zero. Pause via the app automation control; pausing development
must never stop protection or original services.
The heartbeat explicitly respects `paused=true` and must not auto-resume it.

## Commands

Working directory: `C:\Users\Administrator\Desktop\KQUANT-\crypto`.
Interpreter: `C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe`.

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe' scripts/run_hybrid_delivery.py status
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe' scripts/run_hybrid_delivery.py next
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe' scripts/run_hybrid_delivery.py run-ready --receipt-directory outputs/hybrid_delivery/w0_data_20260906_01/receipts
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe' scripts/run_hybrid_delivery.py pause-development
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe' scripts/run_hybrid_delivery.py resume
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe' scripts/run_hybrid_delivery.py prepare-live-approval
```

`verify --receipt <path>` records hashed acceptance evidence. `evidence-report`
prints the current recomputed state. No command sends orders or grants Live.
Inspect ownership before resuming interrupted tasks. Do not repeat expensive fits
with unchanged input/config; preserve every old run and failed attempt.

## Retained Failures and Next Work

The first MC history attempt (`mc_history_20260906_01`) failed before loading
market rows because the loader compared a canonical JSON manifest hash with the
file-byte SHA. The new loader now validates each separately; attempt 02 passed.
No dates, symbols, returns or frozen manifest were changed to obtain that pass.
The Mock protection verifier retains its preliminary Decimal-boundary failure
and the subsequent fixed-source attempt; old evidence was not overwritten.

Next runnable work is T21: bounded MC current/pending portfolio risk valuation,
stress/common-random-path numerical tests and performance, reusing the original
protection/BASE semantics. No risk probabilities are authorized from path-input
smoke tests. T32/T33 native-adapter engineering and T40 observation/control
engineering remain parallel options; actual account operations require A1.
T12 needs a separately owned continuous observer with a predeclared SLO window;
the reused heartbeat is not that collector. No natural labels means WAIT_DATA,
not artificial trades. G2 diagnostics/support validity and calibration policy
still require specific work; T16 formal model consumption remains blocked.

T21 continuation checkpoint: `outputs/hybrid_delivery/t21_numerics_20260906_01`.
Added explicit family-wise Monte Carlo binomial upper bounds, zero/all-event
boundary handling, and separate incremental/high-watermark/day-loss summaries.
The initial risk row cannot be omitted to hide a breach, and same-day budgets
cannot be reset. Actual isolated tests: 27 passed; shared-environment affected
tests: 57 passed, 1 optional SciPy test skipped (covered in isolation).
The first shared run failed because SciPy is absent there; no packages were
installed into the collector environment. Raw successful commands/logs and the
observed initial failure are retained. These are numerical engineering checks,
not risk calibration or G4. T21 remains READY/incomplete.
Integration finding: `CandidatePortfolio.on_closed_batch(allow_entries=False)`
cancels existing pending, so it cannot directly implement MC's no-new-proposals
rule. The next adapter must retain pending and original protection while
suppressing only new future proposals. No original portfolio code was changed.

T21 portfolio continuation: `outputs/hybrid_delivery/t21_portfolio_20260906_02`.
The new adapter now restores the original portfolio and overrides only NEW
reservations; inherited pending, entry, stop-first, gap protection, BASE R,
timeouts, mode exits and day handling remain in the original implementation.
Original midnight-opening/day-change events are recorded, not invented daily
budget resets. Closing summaries also retain original DAILY_LOSS_PAUSE events.
Missing marks/kernels, future pending availability, invalid BASE risk,
over-reservation and discontinuous/unaudited risk rows are rejected.

Read-only review found those input gaps; they were repaired and the isolated
affected suites passed 54 tests. The actual authorized historical run used the
same 32 common paths and frozen A/rules; it started with ZERO positions and ZERO
pending, equity 10000. This is only real-input empty-portfolio path evidence,
not a nonempty portfolio stress PASS. Explicit synthetic cases exercise pending,
protection and midnight gaps. No old run, strategy or evidence database was overwritten.
Run 02 retains source bytes, hashes, independent initial state, risk paths and
test output. T21 still needs new-proposal alternatives, full future-cost stress,
5000-path performance and formal numerical acceptance. No risk sizing is enabled.

Intermediate full regression at `checkpoint_20260906_03` passed 757 tests,
8 skipped and 27 subtests; isolated math passed 47. Subsequent input-hardening
changes are covered by the 54-test isolated run and the affected run-02 log,
not misrepresented as already included in that earlier full-suite checkpoint.

## T21 Future-Cost and Alternative Inputs

Development process-isolation prototype added (`hybrid_math_process.py`), with
actual spawn/slow-worker/deadline/cleanup tests: 2 passed. It owns only its child,
never grants admission, and does not touch original services. This is NOT yet
protection-channel acceptance: real MC integration, result-size/IPC backpressure,
crash and load measurements remain required before connecting a protection loop.

IPC follow-up: pipe receipt now occurs on a separate reader thread, with a 64KiB
JSON response limit instead of main-loop pickle receipt. Five actual process
tests cover deadline, success, oversized result, abrupt exit and redacted error.
Log: `outputs/hybrid_delivery/math_process_ipc_20260906.log`. Production protection
integration and actual MC-load measurements remain unverified; G4 is unchanged.

Actual MC process-load smoke subsequently completed at
`outputs/hybrid_delivery/mc_process_load_20260906_01/result.json`: 20 paths,
four alternatives, double-cost comparison, 737 supervisor polls; measured poll
P95 0.0103ms, max 0.0885ms. Child and reader terminated and hashes stayed stable.
These are function-call durations in an independent supervisor, NOT scheduling
latency, protection execution latency, full 5000-path load or production SLO.
Original protection-service integration remains required. G4 stays closed.

Original CandidatePortfolio stop-path parity now tested while an owned math
child is sleeping: identical trades, costs/BASE R (full trade equality), cash
and flat terminal position versus no-worker reference. Six combined process
tests passed; log `outputs/hybrid_delivery/protection_process_parity_20260906.log`.
This exercises unchanged original code with synthetic bars, not a live service,
quote transport, CPU saturation or production protection latency acceptance.

Deadline follow-up: poll no longer performs terminate/is_alive/join calls;
it only returns a sticky ABSTAIN. Owned-process termination stays in explicit
off-protection cleanup. Seven process/protection tests passed, including a test
that forbids those system operations on deadline polling. Callers must still
schedule cleanup; this primitive is not itself a production supervisor.
Evidence: `outputs/hybrid_delivery/protection_deadline_20260906.log`.

Result isolation follow-up: returned worker dictionaries are deep copies;
caller edits cannot persist into future polls or turn ABSTAIN into authorization.
The actual child-process nested-result mutation test was added. This strengthens
the local component only; no additional task or trading gate is promoted.

Full common-path comparison completed at
`outputs/hybrid_delivery/t21_alternatives_5000_20260906_01`: 5000 paths,
four alternatives, BASE/future-double-cost, 807.266 seconds, exit 0; source hashes
unchanged. The four BASE daily-loss counts are zero, with conditional numerical
upper bound 0.0008760214 under family alpha 0.05 and four comparisons. This is
not calibrated market probability. All eight mean terminal changes are negative.
No size was selected. OHLC/current-rule proxy, synthetic initial state and the
fixed exposed historical window remain explicit. G4 still requires broader risk
event acceptance and nonblocking protection evidence; 807 seconds is not an
online admission deadline. Do not increase freshness tolerance to accommodate it.

Four-alternative actual-path smoke run:
`t21_alternatives_smoke_20260906_03`, 20 common paths, two cost scenarios,
exit 0. Synthetic retained BTC pending plus four ETH proposal quantities
(exact quantities in alternative_inputs.json) are
not account positions or selected trades. Daily-loss event count zero does not
imply zero probability: the conditional numerical upper bound is about 0.19676
at this small path count, and admission remains ABSTAIN. Run 01 failed because
the isolated math interpreter lacks DuckDB; no environment was changed. Run 02
completed but combined alternative aggregates; run 03 separates them by size
and cost. Prior runs retained. Full-scale comparison remains outstanding.

Added `hybrid_mc_comparison_v12.py`: complete common-path risk-event accounting
across the four original quantity alternatives, with explicit family error and
comparison budget. Missing/duplicate/unknown outcomes reject the summary rather
than shrinking its denominator. Zero-quantity risk remains counted. The new
comparison and numerical suites passed 21 isolated tests. This is a contract
component, not yet the complete 5000-path/all-alternative benchmark or G4 PASS.

`outputs/hybrid_delivery/t21_stress_5000_20260906_01` completed 5000
synchronized six-hour paths under BASE and double FUTURE costs in 321.719
seconds, exit 0. Historical returns are from the authorized development window;
the two pending positions are explicitly synthetic, not current account state.
Paid entry costs and BASE risk remain unchanged. This is not a retrospective
all-cost rerun, market performance evidence, or G4 PASS. The measured runtime
does not establish suitability for an online quote deadline.

The independent alternative-input module uses exactly 0, 0.25, 0.5 and 1.0.
It preserves inherited exposure and derives new reservations through original
hard rules, rounding down and skipping below-minimum orders. No alternative is
selected and no sizing consumer is enabled. Shared-path BASE/stress tests verify
existing trades are unchanged. The three affected isolated suites passed 36
tests; formal all-alternative numerical acceptance remains unfinished.

## T32 Offline Stream Decoder

The synthetic-only executionReport decoder passed 58 targeted tests. It keeps
order updates separate from incremental fill facts, validates Decimal values,
identity and millisecond timestamps, and marks unknown/unconverted commissions.
Evidence: `outputs/hybrid_delivery/t32_stream_contract_20260906/attempt_20260905T181729_092160Z/evidence.json`.
Deduplication is bounded, in-memory and epoch-scoped. Authenticated transport,
durable reconciliation and OMS integration are NOT complete; T32/G8 stay open.

## Gates and Owner Actions

Latest stable full checkpoint: `checkpoint_20260906_07`, 863 passed, 8 skipped,
27 subtests; isolated math 64 passed. All commands exit 0 and source stability
and protected baseline checks pass. Partial receipt saved in
`partial_checkpoint_20260906_07`; no task/gate promotion is implied.

T34 rule-cache contract increment: immutable fixture versions with availability,
expiry, environment and expected plan hash. Older or conflicting refreshes are
rejected; new versions invalidate old plan bindings without deleting history.
Three tests passed. Actual exchangeInfo normalization/fetching and persistence
are not integrated, so this cache is explicitly mock-only and T34 remains open.

Actual public rule inventory fetched successfully from the official data-only
Spot endpoint for BTC/ETH/SOL at `public_rules_20260906_01`, exit 0. Raw response
SHA256 `14cd614e60f960bd1ed05627bc1a8dbffdb5b4c44bf4d8c201f6cc02cc3ce088`.
Local request/receipt timestamps remain explicitly local; no native source event
timestamp was invented. All three expose additional percent-price, order-count,
order-list, algo/amendment and specialized-order filters requiring context or
implementation. This is inventory, not a claim every filter applies to IOC.
No credentials/account/production order endpoint used; execution remains false.

IOC audit now includes exchange-level filters and LIMIT support, and hashes both
symbol and exchange constraints. Missing exchange context cannot silently pass.
Eight rule-audit/cache tests passed. This is still a preflight inventory, not
fully implemented account-aware venue admission.

Order-count input contract added: current open orders plus reserved submissions
plus the proposal must fit the limit. Missing, stale, future, wrong-symbol,
unreconciled and algo-incomplete counts block. Nine tests passed. This consumes
explicit offline inputs only, not authenticated account evidence, and is not yet
wired into actual venue admission. T34 remains partial.

The count contract is now wired into read-only IOC audit for MAX_NUM_ORDERS,
with explicit current time and max age. Missing time keeps the unresolved
context blocker; no actual account verification or admission is inferred.

Public rule archive primitive added: content-addressed versions, duplicate
identity checks and read-time integrity validation. Six archive/cache tests
passed. Interrupted/corrupt files fail closed and are not overwritten. This is
not a production durable cache or authenticated provenance verification; actual
fetch integration and recovery acceptance remain pending.

Public fetch/archive integration subsequently ran successfully at
`public_rules_20260906_02`: actual BTC/ETH/SOL response, content-addressed archive
and read-back payload equality verified, exit 0. Receipt clock remains explicitly
local milliseconds, not a native source event. Archive identity
`8e5ab2ca97ab785de5090c30ce0da2b0bec101c43d701bf4a0a201bb708abd6a`.
No existing response or runtime was overwritten. This does not establish a
continuous refresh service, trusted clock freshness or execution admission.

Captured-rule IOC replay completed at `ioc_rule_replay_20260906_01`, exit 0,
without network/account access. All three explicitly synthetic proposals passed
the implemented scalar checks but retained percent-price and account/order-type
context blockers. Original raw response hash was verified before use. This is
not evidence of currently executable prices, account eligibility or T34 PASS.

Applicability refinement: NEW standalone LIMIT IOC does not create algo orders,
order lists or amendments, so those specialized symbol limits are separated as
not applicable for this one operation, not waived for later protection orders.
Nineteen related tests passed; captured-rule replay 02 retains only the relevant
unresolved context for this scope. No protective-order validation is implied.

Percent-price contract now accepts explicit side-specific reference inputs with
symbol/time/window validation. Weighted-average fallback requires explicit
absence of an exchange reference; unknown/stale inputs block. Two focused tests
passed and the function is connected to the read-only IOC audit. Reference
provenance is caller-supplied, not independently authenticated; no admission is
granted and actual reference acquisition remains unfinished.

Official reference-path capability audit (2026-09-06): documentation identifies
GET /api/v3/referencePrice, GET /api/v3/executionRules and the referencePrice
stream. Two bounded public requests on data-api.binance.vision for BTCUSDT
returned HTTP 404 (PowerShell exit 1 each). This proves only that those routes
were unavailable on the selected data-only host, not that the symbol has no
reference price/rule. No fallback price or absence assertion was synthesized.
Production/account endpoints were not tried. Reference acquisition remains a
scoped T34 blocker pending a supported authorized public route.
Source: https://raw.githubusercontent.com/binance/binance-spot-api-docs/master/faqs/price_range_execution_rules.md

### T32 Recoverable Offline Journal Increment

Stable-source rerun `checkpoint_20260906_06` subsequently PASSED: 841 Crypto
tests, 8 skipped, 27 subtests; isolated math 64 tests; diff and baseline audits
exit 0. All captured source hashes remained unchanged. Partial receipts were
recorded at `partial_checkpoint_20260906_06` without promoting T21/T32 or G4/G8.
Checkpoint 05 remains an immutable failed attempt, not overwritten.

Checkpoint 05 executed 841 Crypto tests successfully (8 skipped, 27 subtests),
and its isolated math, diff and protected-baseline commands exited 0. However
the aggregate checkpoint FAILED its source-stability check: the partial-receipt
registration script was edited during verification. This checkpoint is retained
as failed and must not promote a task. A stable-source rerun is required before
registering this increment as verified evidence. Decimal-context isolation in
the journal is covered by the 67-test targeted suite.

The journal now also compares unique incremental fill quantities and quote
amounts against cumulative reports. Missing fills are reported, never inferred;
late fills may repair quantity completeness but cannot clear unknown or
unconverted commission evidence. Stored normalized records are checked against
replay. These are internal synthetic facts only, not account reconciliation.

`hybrid_offline_stream_journal.py` adds an independent SQLite synthetic-event
journal. Replay and append share a write transaction; a failed insert cannot
consume a fill. Restart preserves duplicate and conflicting-event detection.
Changing connection epochs requires a separate journal and does not silently
reset identity within an existing one. Targeted decoder/journal tests: 62 passed.
An initial close-before-rollback error was detected and repaired. This remains
a bounded replay implementation, not account reconciliation or live transport;
cross-epoch reconciliation and production throughput are still unverified.

Latest checkpoint `outputs/hybrid_delivery/checkpoint_20260906_04` passed:
832 Crypto tests, 8 skipped, 27 subtests; isolated math 64 tests. All four
commands exited 0, source hashes stayed unchanged during the run, and protected
baseline audit passed. Below older checkpoint counts are retained as history,
not the latest suite. No unrelated stock tests or frontend build were rerun.

ENGINEERING: local components verified, full integration not complete.
DATA: exposed proxy development eligible; forward quote labels WAIT_DATA.
MODEL: TRAINED_DEV_ONLY / ABSTAIN, G2 not passed.
PERFORMANCE: UNPROVEN; old A descriptive results negative, not Hybrid success.
LIVE: DISABLED; not ready for A2.

Actual final regression: Python312 Crypto **739 passed, 7 skipped, 27 subtests
passed**, exit 0, 155.859 seconds including process overhead. Isolated math
environment **28 passed**, exit 0, 6.453 seconds. `git diff --check` and the
post-regression baseline audit both exit 0. Protected source hashes and original
four-file tracked diff remain identical. No frontend or stock production code
was edited, so unrelated stock tests and React build were not rerun.
Exact commands, interpreter paths, durations, source hashes and raw logs:
`outputs/hybrid_delivery/checkpoint_20260906_01/checkpoint.json`.
Actual status/next/evidence-report/prepare-live-approval CLI calls all exit 0;
approval readiness still lists missing G2-G9 and returns `NOT_READY`.

## Additional local rule and health checkpoint

T34 actual public refresh/index integration exited 0 at
`outputs/hybrid_delivery/public_rules_20260906_03/evidence.json`: BTC/ETH/SOL
share new content identity fb2d8f6f5f6ce766db977421380b7e0f92546c855c5f155cc345919c5dd1a05b.
Response receipt is captured before disk/JSON work; source event time remains
unknown. The explicit `--index` path uses independent public_rule_observations
storage and millisecond-named freshness arguments. Five-second local read-back
check is only this diagnostic, not an execution freshness policy. No account,
reference-price or production permissions are inferred.

T34 independent persistent public-rule index added. It preserves observed versions,
rejects same-receipt conflicts and stale/future latest data without falling back
to an older convenient version, and checks content hashes on read. Five index/
archive tests passed. Actual archived public capture
8e5ab2ca97ab785de5090c30ce0da2b0bec101c43d701bf4a0a201bb708abd6a registered
three symbol rows in `work/hybrid_delivery/public_rule_index`. This is historical
local-receipt evidence, not fresh exchange availability or account authorization.

New T21 evidence audit actually exited 0 at `t21_readiness_20260906_01`.
It rechecks current source hashes, archived file integrity, fixed 5,000-path
budget, matching record hash, owned-process completion and recorded synthetic
parity. One focused test confirms that source drift fails consistency and even
consistent artifacts never grant G4. This is a prerequisite audit, not a complete
gate verifier; formal admission and production protection scope remain explicit.

T21 full owned-process load test completed, exit 0:
`outputs/hybrid_delivery/mc_process_load_20260906_03/result.json`.
5,000 paths completed in 480.828s; 480 synthetic original-protection checks all
matched reference trades/cash/positions. Protection function P95 0.0001045s,
maximum 0.0002619s; poll P95 0.0000071s over 45,956 polls. Child and reader stopped,
captured source unchanged. Record hash exactly matches the previous frozen
5,000-path archive; gzip container hash differs, as expected for a fresh file.
This is an independent parent/child synthetic protection workload, not production
scheduling/network/venue protection availability. No size selection or financial
gate; G4 remains false pending remaining formal admission/diagnostic scope.
The existing task event store contains this bounded partial evidence.

T12 actual bounded public observation completed with exit 0 at
`outputs/hybrid_regime_v1/clock_segment_20260906_02`: 80 time-qualified/consumed
quotes, zero rejected, no detected continuity gaps, zero opportunities and zero
new fill/label records. No same-name observer process was found before launch.
The new 30-second segment preserves source event times and uses independent
storage; old services/logs are untouched. The existing delivery store records
this partial evidence. It does not satisfy 72h continuity or a natural filled
label lifecycle, so T12 remains WAIT_DATA and G2 stays closed.

T40 now inspects the existing DEV artifact metadata without loading a model.
Actual probe `health_probe_20260906_03.json` reports model WAITING/DEV_ONLY_ABSTAIN,
metadata hash 1502562676493f43ad3c3d691fd1b3fed5ea19276c45c944397f23b80a5ca29a,
and API provider disabled. Twelve metadata/health tests passed. This is permission
metadata observation, not posterior integrity, calibration or live-model health.
Orders/protection remain unknown; no model consumer was enabled.

T34/T40 evidence registration now includes the actual probe, transport, journal,
CLI and export tests, captures its own source and log hashes, and preserves a
timeout result rather than losing the receipt. Updated bounded run
`outputs/hybrid_delivery/rule_health_20260906_02` passed 55 tests, exit 0, and
appended a partial event to the existing task store. No new scheduler or task
promotion. This targeted receipt does not replace the earlier full checkpoint.

T34 order-count time validation rejects negative current timestamps and negative
availability timestamps even if their difference appears fresh. This closes an
input-contract bypass; no account access or threshold changes are introduced.

Full integration checkpoint 09 passed: 920 Crypto tests, 8 skipped, 27 subtests;
isolated math, diff check and frozen baseline audit all exit 0. Captured sources
did not change during tests. Evidence and existing-task partial receipt are at
`outputs/hybrid_delivery/checkpoint_20260906_09` and
`outputs/hybrid_delivery/partial_checkpoint_20260906_09`. No gate promotion;
actual account/network and notification approvals remain pending as scoped in A1.

T32 read-only reconciliation now reports stored report-key corruption as well
as normalized-payload mismatch, consistent with append refusal. Sixty-nine
decoder/journal tests pass. Actual durable restart/late-fill/duplicate scenario
rerun exited 0 at `outputs/hybrid_delivery/t32_recovery_20260906_02`; unknown
commission conversion remains a blocker. This is synthetic evidence, not G8.

T32 append now revalidates stored report keys and normalized events while replaying
under its existing transaction. Corruption blocks new writes without repairing
or overwriting history. Decoder/journal tests: 69 passed, exit 0. Initial test
edit misplaced a restart assertion and yielded two failures; restoring the
original test boundary resolved them without weakening integrity checks. Scope
remains independent synthetic journal, not account reconciliation or live OMS.

T21 identity validation rejects boolean/floating path IDs and boolean quantity
multipliers instead of allowing Python equality to alias them with integer IDs
or full-size alternatives. Twenty-seven comparison/numerical tests pass in the
isolated environment. Valid registered paths and comparison budgets are unchanged;
no resampling, threshold change or gate promotion occurred.

T21 worker startup cleanup now closes owned pipes when process start fails and
cleans up the owned child if reader startup fails. Ten focused process/startup/
protection-isolation tests pass (exit 0). Poll/protection callback behavior is
unchanged; cleanup remains outside that callback. No existing service process
is targeted. These injected startup tests do not establish a production SLO.

T21 zero-size existing-loss regression now evaluates the actual portfolio adapter
with a synthetic preexisting daily loss. `m=0` preserves the snapshot, reports
the daily-line breach and absolute drawdown despite zero incremental drawdown,
and remains ABSTAIN. Isolated alternatives + numerics suite: 23 passed, exit 0.
No original risk threshold or running account state changed. This is a synthetic
boundary test, not a new market performance result or G4 completion.

T21 archived replay audit actually exited 0 in the isolated math environment:
`scripts/audit_hybrid_archived_mc.py --output outputs/hybrid_delivery/t21_archive_audit_20260906_01`.
All 5,000 archived path IDs, compressed hash and record hash match; four BASE
daily-loss comparisons exactly reproduce the prior comparison.json. No paths
were sampled, no size selected, no historical/evaluation interval opened. This
checks numerical replay only; G4 remains false and broader risk scope unresolved.

Fixed-endpoint HTTP-only transport removes unnecessary client HTTPS setup for
this loopback-only probe; it does not disable TLS verification for any external
provider. Actual `health_probe_20260906_02.json` records HTTP 200 in 0.157s,
client setup 0.0s at observed timer precision, API provider disabled. Twenty-eight
related tests pass. Transport rejects other hosts, paths, schemes, query strings
and credentials, does not forward arbitrary headers, and closes the connection.
This is one performance sample, not a latency percentile or production gate.

Probe evidence is now exportable with `--evidence` to a new, non-overwriting
delivery file containing source hashes and journal ID. Actual sample 6 is saved
in `outputs/hybrid_delivery/health_probe_20260906_01.json`: client initialization
4.219s, headers 4.891s, budget exceeded. This identifies client initialization
as the dominant measured delay in this sample, not the root cause inside the
client or prior runs. A subsequent guard prevents issuing HTTP after initialization
already exhausts the unchanged budget. No live or performance gate changes.

Local probe timing refinement: sample 5 completed in 0.938 seconds, with client
initialization 0.797 seconds and headers/body available at 0.938 seconds. It
reports API_RUNTIME_PROVIDER_DISABLED and data WAITING. Earlier budget failures
remain retained; this successful measurement does not explain their root cause.
Twenty focused tests pass, including a controlled budget-exceeded case. The
three-second policy is unchanged. Timing fields now distinguish initialization,
response headers and decoded body; no market freshness is inferred.

Provider-aware local probe: 19 related tests pass. Direct public local health
inspection reports the API runtime's Binance provider disabled; this does not
describe independent collectors. The probe only maps explicit disabled/degraded
states to WAITING/FAILED; a reported live status never proves market freshness.
One actual probe returned HTTP 200 but exceeded its read budget (4.734 seconds),
so sample 3 correctly remains UNKNOWN/INVALID_HEALTH_RESPONSE. No timeout was
relaxed and no service was restarted. Provider diagnostics are allowlisted.

T40 loopback probe now actually GETs only `127.0.0.1:8010/api/health`, without
credentials, proxy environment or redirects. The recorded sample 2 returned
HTTP 200 in 0.859 seconds. This proves HTTP responsiveness only; data, model,
orders and protection remain UNKNOWN. No service was restarted. Sixteen related
tests passed after replacing oversized pytest parameter IDs with short IDs;
the initial run had 15 passes and two setup errors, not a business-contract pass.
CLI: `scripts/run_hybrid_health.py probe`; status remains a historical report.

T40 incremental journal: `scripts/run_hybrid_health.py record` and `status`
actually exited 0 against `work/hybrid_delivery/health/hybrid_health.sqlite3`.
The first sample deliberately reports UNKNOWN for all five components: no live
probe or collector integration is claimed. Status identifies its result as a
historical report, not fresh health. Nine targeted health tests pass, including
SQLite close/reopen deduplication, clock conflict rejection and rollback after
an injected write failure. This new journal is separate from original writers;
external notification and full T40 acceptance remain incomplete.

Full checkpoint `outputs/hybrid_delivery/checkpoint_20260906_08/checkpoint.json`
subsequently passed: 888 Crypto tests, 8 skipped, 27 subtests; isolated math,
diff check and protected baseline audit exit 0. Captured source hashes stayed
unchanged during verification. Existing task store includes the partial receipt
in `partial_checkpoint_20260906_08`. No model, performance or live gate promoted.

`outputs/hybrid_delivery/rule_health_20260906_01/evidence.json` records
33 targeted tests passed, exit 0, unchanged tested source hashes. This is not a
replacement for the prior full regression checkpoint. T34 now checks explicit
reference selection, reference windows, observation age and order counts using
read-only caller inputs. These inputs are not authenticated account evidence.
T40 has a pure allowlisted health-summary contract: absent, stale or future
observations remain UNKNOWN; raw errors and URLs are not copied; heartbeat time
alone does not change the material-state hash. There is no external notification
or production monitor integration in this increment. Neither task is promoted
to VERIFIED. The partial receipt is appended to the existing delivery store.

ENGINEERING: local contracts pass; complete integration remains partial.
DATA: strict online lifecycle and account evidence remain incomplete.
MODEL: DEV_ONLY / ABSTAIN; no automatic consumer enabled.
PERFORMANCE: UNPROVEN; no threshold or execution permission changed.

Consolidated A1 is in `HYBRID_DELIVERY_A1_V1_2.md`: actual venue entity/eligibility,
testnet and production-readonly scope, host/process/deployment/fees/notifications.
No secrets in chat. Pending approval blocks only respective external operations.
The coding agent cannot submit real orders or approve its own production activation.
# Incremental Observation Checkpoint: 2026-09-06, Snapshot 02

Read-only evidence: `outputs/hybrid_delivery/continuous_audit_20260906_02/report.json`.
The independent SQLite snapshot passed ledger integrity checks with no errors:
9,196 committed quotes, 22 closed batches and 22 separate commit observations.
Snapshot SHA256: `d136a5d1eb588ae9a7a690d117636797f6b470a9ca67d79a8efa6b806cebffa2`.
There were zero technical opportunities, fills or labels. This is not an
unfilled/maturing-label backlog. BTC recorded 22 RANGE decisions; ETH recorded
22 UP_TREND decisions; SOL recorded 20 TRANSITION and 2 UP_TREND decisions.
Regime eligibility alone is not an entry trigger.

Descriptive qualified-time coverage within the committed-event envelope was
98.58% BTC, 99.09% ETH and 97.48% SOL. These are not preregistered SLO results:
the exact preregistered monotonic origin is missing, rejected raw messages are
outside ledger counts, and this interval does not establish 72-hour availability.
G3, model and performance gates remain false; exchange-fill evidence is absent.

An OS process probe independently confirmed observer PID 41956 with Python312
alive at this checkpoint. Its persisted status was RUNNING, failure null and
execution disabled, after 6,528 seconds. This is a point-in-time observation,
not a continuing liveness guarantee. No process was stopped or restarted.

Targeted verification command (crypto working directory):
`Python312/python.exe -m pytest -q tests/test_hybrid_observer_run_audit.py tests/test_hybrid_mc_evidence_audit.py`.
Actual result: 3 passed in 0.78 seconds, exit 0. This does not supersede the
recorded full-regression scope or assert full live-approval readiness.
# Observation Failure And Recovery: 2026-09-06

The earlier live checkpoint below is historical, not current liveness.
`continuous_24h_20260906_01` ended FAILED with ConnectionClosedError after
6,949.55 seconds. Its final independent audit passed ledger integrity with
9,558 quotes, 23 closed batches and zero opportunities/fills/labels. Close codes
were absent from the old log, so the specific disconnection cause is unknown.
This failed run does not satisfy 24h or 72h acceptance and is not overwritten.

Implemented exact preregistered monotonic observation bounds, persisted before
bootstrap, bound by manifest/registration/event hashes. Audits now preserve the
full planned denominator, not just first/last quote time. Added sanitized close
code diagnostics; no timestamps, freshness, entry, protection or risk rules changed.
The new real 45-second smoke run consumed 53 qualified quotes and passed the
independent window audit. Full Crypto regression: 948 passed, 8 skipped,
27 subtests. Isolated math, git diff check and protected baseline audit exit 0.
Evidence: `outputs/hybrid_delivery/checkpoint_20260906_12/checkpoint.json`.

New independent observation: `outputs/hybrid_regime_v1/continuous_72h_20260906_01`.
Launch PID 32672, requested 259,200 seconds. It does not inherit successful uptime
from the failed run. Future failure still ends the run; no recovery or protection
availability is inferred from a process restart. G3, model and performance remain
unpassed; execution and mathematical filtering remain disabled.
# Latest Online Outcome: Repaired Series Relaunched

`series_smoke_20260906_04` passed a real bounded collection/stop run with 147
qualified quotes and independent ledger integrity verification. New current
series: `outputs/hybrid_regime_v1/series_72h_20260906_03`, manager launch PID 42976,
72-hour total budget, max 12 separate segments. Long-run acceptance remains
unproven; no natural opportunities/labels, mathematical admission or real orders.
Regression checkpoint 14: 956 passed, 8 skipped, 27 subtests, all four checks exit 0.
The terminated series and IO failure described below remain historical evidence.
Series_02 ended correctly on REST ConnectError; a narrow repair now includes that
connection error in bounded new-segment recovery, alongside WebSocket closure.
No HTTP authorization errors or clock contract failures are retried. 23 targeted
tests passed after this change; prior full-regression evidence is not relabeled.

The manager (42676) and child (27120) have both exited. A Windows sharing-related
PermissionError during status replacement killed the manager and left a stale
RUNNING heartbeat. The traceback is retained in
`outputs/hybrid_delivery/series_launch_20260906_01/launch.stderr.log`.
The child ended on invalid clock probe duration after 1,504.38 seconds; its
terminal audit passed with 690 quotes, 5 closed batches and zero opportunities.

Implemented bounded status-write retry plus owned-child shutdown on persistent
failure and an independent failure record, preferred by the status command.
Fault tests cover transient/persistent failure, no duplicate child and preserved
false gates. No current long observation is asserted. Original data, A/B, clocks,
protection, account and live admission remain unchanged. Earlier restart evidence
below is historical only.

After the failures below, five new clock probes passed the unchanged contract.
The third real smoke (`series_smoke_20260906_03`) consumed 122 qualified quotes,
stopped its owned child at the duration budget and exited 0. Its independent audit
at `outputs/hybrid_delivery/series_smoke_audit_20260906_03` passed ledger integrity.
New series `outputs/hybrid_regime_v1/series_72h_20260906_01` was launched with
manager PID 42676, 72-hour total budget and at most 12 separate segments.
Actual repeated-network-recovery acceptance remains unproven; unit tests and a
normal-stop real smoke are not that proof. G3/model/performance remain unpassed.

PID 32672 is absent; `continuous_72h_20260906_01` failed after 11,401.82 seconds
with ConnectionClosedError, no close-frame codes, 5,731 qualified quotes and
38 closed batches. Opportunities/fills/labels remain zero. Earlier RUNNING
checkpoints below are historical, not present liveness evidence.

Bounded segmented recovery is implemented, not accepted as a continuous service.
It preserves failed runs, caps attempts and duration, never combines segments as
uninterrupted 72h, and strips private credential environment variables from child
processes. The first real short run failed clock-probe duration; its deadline
status masking defect was fixed and covered by regression. The second short run
correctly stopped on ConnectError. Long observation was withheld until the
successful third smoke described above.
Public DNS resolved, and a separate /api/v3/time returned 200 in 8.855 seconds;
this does not establish the required per-probe timing contract.

Evidence: `outputs/hybrid_delivery/checkpoint_20260906_13/checkpoint.json` and
`outputs/hybrid_regime_v1/series_smoke_20260906_01`, `series_smoke_20260906_02`.
954 Python tests passed, 8 skipped, 27 subtests; isolated math, diff and protected
baseline audits passed. Engineering is partial, online data WAIT_EXTERNAL,
model DEV_ONLY/ABSTAIN and performance UNPROVEN. No mathematical or live gate passed.
