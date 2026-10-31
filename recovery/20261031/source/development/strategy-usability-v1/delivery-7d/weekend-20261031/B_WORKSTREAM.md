# Workstream B: Immutable Generation Handoff

## Parent Integration, October31 23:30 Beijing

The section below is historical handoff evidence, not the final integrated hash.
Parent fixed the legacy None-generation validation path and real minute-only
owner notifications erasing same-scope native references. References retain their
original timestamps; explicit failure/scope change still invalidates them.
Bound DataRoot is validated at real Lane construction; current map bytes and
environment identity are checked at admission/finalCAS. Same-size map mutation
and environment drift reject. Exact source-path names are deduplicated before
OS resolution; hashes remain byte-based.76 affected regressions pass.

Actual short6:574/574reads,100original-deadline pending recoveries, all11points
recorded, but finalqueueP9514.266s FAIL. This is not an hour or performancePASS.
The short4 cProfile instrumentation conflict killed point11; preservedFAIL,
removed wrapper, replaced by passive phase timing. No production writes/start.
Read the single weekend closeout and EXECUTION_EVIDENCE.json for current identity.

## Superseding Fence Handoff: 2026-10-31 22:45:56 +08:00

Status: code frozen for parent integrated short. No B topology/hour/API run.
This section supersedes the 22:25 freeze and its 52-test completeness claim;
the historical section and old hashes below are retained, not current identities.
Seven-day FAIL and last topology 9.093s P95 FAIL remain unchanged.

### Final Affected Validation

- Actual selected assembly bootstrap plus explicit KQUANT_TEST_WEEKEND_OVERLAY
  equal to the absolute delivery-7d/weekend-20261031 directory.
- KQUANT_TEST_FROZEN_PROJECTION was the existing 7896 deployment-projection JSON;
  this is an isolated overlay test, NOT a newly accepted release of that identity.
- Final nine-module run: **65 passed in 11.05 seconds**, exit 0. Exec session
  64950 completed; no owned test session remains running.
- Modules: test_input_commit_fence, test_generation_handoff, test_first_hour_runtime,
  test_first_hour, test_first_hour_journal, test_prepared_minutes,
  test_source_preparation, test_decision_preparation, test_method_snapshot.
- Earlier focused run: 25 passed / 7.74s; expanded run: 64 passed / 11.10s.
  The subsequent partial-action-batch test initially failed (64 pass / 1 fail,
  11.31s): its TEST_ONLY transport returned a list rather than the native-shaped
  items object. Correcting that fixture, without weakening source validation,
  produced the final result above. These are test wall times, not queue P95.
- Loaded modules were printed and verified: the fence and four producer patches
  resolve to weekend-20261031/patches/kquant; options_opening_trend_store resolves
  to opening-first-hour/first_hour_store.py. The temporary weekend store copy was
  deleted; both direct first_hour_store and mapped kquant consumers use the actual
  eleven-point adapter file, not an older BASE store.

### Fence and Supported Writers

Exactly one qualified module owns the process-local RLock:
`kquant.options_input_commit_fence`. Acquisition waits at most 0.05 seconds and
raises typed InputCommitBusy; nested acquisition is reentrant. No new queue,
thread, database, schema, network collector or increased timeout/limit was added.
Ordering is fence -> journal -> lane condition. Expensive admission, network
requests and result serialization remain outside the gate. Final current file,
minute, decision, persisted price-fact, method and clock checks occur AFTER fence
acquisition; files are still checked outside the SQL transaction and lane
condition. The fence is held through the existing CAS transaction commit.

Covered publication paths:

1. Actual common.save_bars, including save_bar delegation, worker push writes and
   the existing RecoveryLane evidence writes. Serialization is before the fence.
2. first_hour_minute_decisions.append_many/append: hash/serialize before fence,
   retain gate until SQLite commit.
3. options_price_action_source.commit_action: gate precedes config lock and covers
   coverage-file replacement and index commit, before later owner notification.
   A later busy action in a batch does not prevent earlier committed notifications.
4. options_price_facts.persist_bindings/persist_binding: gate spans both fact rows
   and transaction commit. Actual worker _price_fact_quotes takes fence BEFORE its
   existing journal guard, preventing lock inversion.
5. Evaluation-attached facts: journal.finish/finish_many and actual eleven-point
   store.persist hold the fence through the transaction. Low-level
   persist_prepared_in_transaction requires an already-held outer fence; it cannot
   falsely release a gate before its caller commits.

The generation now also binds a bounded exact payload token for relevant persisted
instrument/session price facts. Changes during preparation or before final CAS
reject the old generation. This adds reads and must be measured in parent topology;
no whole-pool latency improvement is claimed from unit-test duration.

### Busy Failure Behavior and Race Evidence

- Four controlled real-writer cases (minute, canonical decision, price fact,
  action coverage) commit while computation is paused, then withhold notification.
  The Lane rejects old-generation completion and re-admits from actual changed
  inputs before notification is released.
- Four complementary cases pause actual journal.finish_many after final validation
  while the fence is held. Every real producer times out before durable mutation;
  it succeeds when retried after CAS releases the fence. Real Worker/Lane
  constructors and real SQLite/file operations are used, not __new__/SQL mocks.
- Actual Worker._drain_events/consume now retains ONE currently dequeued event
  and its originally parsed bar on InputCommitBusy. It returns to the existing
  owner tick, leaves following events in the original sink and clears the item
  only on success. The test forces two busy ticks, verifies no persisted/consumed
  loss, then verifies exact raw payload and original received_at after retry.
  Busy counters/WAIT_COMMIT are explicit. Drain bounds are unchanged.
- Existing RecoveryLane already catches TimeoutError through OSError and retains
  its completion and pending batch. A real recovery-owner test forced busy I/O,
  then committed the same captured result with ONE transport call and unchanged
  deadline. No extra recovery queue or provider request was introduced.
- Action busy keeps the saved raw observation and original claim, without an
  immediate second request. Tests verify unchanged claim before existing expiry,
  re-claim eligibility after expiry, and delivery of earlier successful batch
  notifications. It does not claim a failed coverage commit succeeded.
- Existing preflight price-fact retry keeps captured quotes and its original
  bounded attempts; no repeat network request is added by the fence.

### Explicit Residual Boundaries

This is process-local ordering of the listed normal writers, NOT an atomic
cross-database snapshot or cross-process lock. Manual SQL/file writes, separate
process writers, the unused private price_facts._persist helper and unregistered
future writer APIs are unsupported by this fence. Frozen method/reference/config
files must remain protected; arbitrary external mutation after final validation
is not made atomic. New writers must acquire this same qualified fence before
any journal/lane/SQL lock and retain it through commit.

Clock publication remains its existing independent owner; final transaction
clock/time guards are retained. This work does not claim to lock NTP publication
or make arbitrary clock changes atomic with SQLite. Current-source approval and
expiry rules are not relaxed.

One retained raw event is in-process ownership, not durable buffering against
process/power loss. Existing durable recovery remains responsible for missing
input after restart, with original deadlines. Busy acquisition and fail-closed
retries can increase latency; full-list contention/fairness, query cost and busy
rates still require the parent's integrated short. No performance PASS, API
capability PASS, actual-window PASS or release approval is supplied here.

### Copy Provenance

Only these effective modules were copied into weekend patches (BASE unchanged):

| File | Copied From | Parent SHA-256 |
| --- | --- | --- |
| options_one_minute.py | legacy-status-fix/patches/kquant | dac725f6bded052453e064dff05e04fdae164bfac30a09803b6995eac72bd255 |
| options_one_minute_runtime.py | monday-signal-llm/fact-commit-followup/patches/kquant | 1ad6ec92188eff7110a55c3c2aaba9ace4a970b749536073177878ed1486f2ad |
| options_price_action_source.py | source/development/workspace/kquant | d88113c673b12df48ed0baa6b84332de02f63ee0e96b7465d5d83ea96d330c89 |
| options_price_facts.py | source/development/workspace/kquant | 86a0add0530f9bd2fb4cddafbbf753b5209e2feabb34ff17a2546f6858c1bbc |

### Current Frozen Files

Paths relative to delivery-7d. This table replaces the historical eight-file table.

| File | SHA-256 |
| --- | --- |
| opening-first-hour/prepared_generation.py | 0496d9af2980c3711e2951714bb8635882c12a27af4df24266d8e0a5bf2cd620 |
| opening-first-hour/prepared_minutes.py | 56caada6a8eee39242b8d95c332f54afaab64668c16025c74bf65658863a9664 |
| opening-first-hour/first_hour.py | e117b776fb54ed160d0b90cea3a611b18ff3b6294a2048de057c39dbf47b8840 |
| opening-first-hour/first_hour_runtime.py | 8eca98137bd3b91c6c35eabd47b4678a54a13e9715be13536052435d53900b86 |
| opening-first-hour/first_hour_journal.py | df656bf1af848e8ce4ee9fa53d76f9a110a0c3c54a289590b3cd85112895ec88 |
| opening-first-hour/first_hour_minute_decisions.py | ca8d91823fbe39aff5ade2447215238b84678cd3d1e0a59000a5161623fe224d |
| opening-first-hour/first_hour_store.py | d5df20a181bd871093def04d9e7c0f46604dcb5d81e4dae79fd53d8e971e3b2e |
| opening-first-hour/method_snapshot.py | 525b5cf4060498a41c630fbd03a8ea1c24bc6fd31bc1070d6c08f373002929b2 |
| opening-first-hour/test_generation_handoff.py | b1ec1879299e527bd41474e806a1757d4f50ae0e1fc37ffd5102dfd3d701ca2f |
| opening-first-hour/test_input_commit_fence.py | 41488dd4da866f2750fe37e91665e8f73306dfca9711a7b81ccc043d2426cf29 |
| weekend-20261031/patches/kquant/options_input_commit_fence.py | fa7e4a4b810681f8795249e8b72c3e19e71ff713bf0b6c5b6695f7fe4a7011b1 |
| weekend-20261031/patches/kquant/options_one_minute.py | 79db421351647fcf9b574cdba8b1d64d4477fa89bb916e3a51718afa8049b2a1 |
| weekend-20261031/patches/kquant/options_one_minute_runtime.py | fbc510728005e878256255d9692df27c3db070f04209318874b0a288df4537ab |
| weekend-20261031/patches/kquant/options_price_action_source.py | c316e2ff4011d45ac1ad2f877955631f591641263233a6575afceb7e58e25a58 |
| weekend-20261031/patches/kquant/options_price_facts.py | 5e92cea06943743c241dde8cbd9c08079c40636cf96310f52a015c763effcef8 |

No production payload, business database, manifest, approval or top RESUME edited.
All mutating B work is stopped for parent integration; no topology was started.

## Historical 22:25 Handoff (Superseded)

Code handoff/freeze observed: 2026-10-31T22:25:04+08:00.
Scope: isolated opening-first-hour preparation/runtime/journal and affected tests.
Historical seven-day FAIL and the prior 9.093-second queue P95 FAIL remain unchanged.
This document is B evidence only, not a release acceptance or whole-system PASS.

## Implemented

- Admission now assembles the durable minutes, decisions, reference, legal minute
  selection and shared aggregation once. It freezes that object and hands it to
  the existing single compute lane after durable admission supplies the actual
  input generation. Compute does not call `_checkpoint_inputs` again.
- The handoff binds instrument/session/checkpoint/scope, input fingerprint and
  generation, exact minute/decision payload tokens, source file content hashes,
  method applicability and receipt expiry, policy identities, current clock
  attachment identity, preparation time and the original deadline.
- Both S0/S1 and Call/Put share minute selection and aggregation. S0 reference
  validation and S1's independent intraday contract still run at compute time.
  A missing S0 cross-day reference does not preclude a complete S1 result.
- Before compute and before commit, bounded durable reads compare exact bytes;
  no stat/size-only or latest-watermark acceptance. File validation and source
  assembly are outside the condition lock and SQL writer. Same-size edits,
  source changes, policy changes, time boundaries and clock changes invalidate
  the object and re-admit the original checkpoint.
- Final commit serializes notification epochs with the existing generation CAS.
  The lease also checks original deadline, preparation validity and live in-memory
  clock identity. No NTP/SDK/system query occurs in this check.
- Equivalent updates can abandon and re-arm the same lease without manufacturing
  a new semantic generation or stranding LEASED work. A stale lease cannot release
  or finish a different admitted generation. WAIT_INPUT registration still checks
  the notification epoch after registration.
- Restart reconstructs the volatile handoff from existing durable jobs. LEASED
  rows are re-armed with unchanged generation/deadline under a conditional update.
  No new queue, table, database, schema, limit, timeout or thread was added.
- Temporal admission is part of the semantic fingerprint: an already stored future
  receive timestamp becoming admissible is a new preparation, even with identical
  raw bytes. Receipt expiry is not inferred solely from the method declaration.

## Measured Verification

All tests use temporary, separated minute/research paths. The fixture constructs
`OneMinuteResearchWorker` and `TrendLane` normally, supplies an explicit TEST_ONLY
transport, and uses real worker `_record`, durable admission, lane threads,
calculators, persistence and journal CAS. It does not use `__new__`, replace the
entire lane tick, call an API, or seed business stores.

Final affected run used actual `opening-first-hour/assembly/bootstrap.py` and the
existing 7896 parent deployment projection, not merely base-workspace imports:

```text
52 passed in 5.85s
exec wall time 7.176s, exit 0
```

The eight selected test modules were `test_generation_handoff.py`,
`test_first_hour_runtime.py`, `test_first_hour.py`, `test_first_hour_journal.py`,
`test_prepared_minutes.py`, `test_source_preparation.py`,
`test_decision_preparation.py`, and `test_method_snapshot.py`.

The new handoff module contains 16 passing cases. A preceding bootstrap-loaded run
of those cases alone returned `16 passed in 4.85s`, exit 0. The final run's slowest
five test calls were 1.13s (actual worker/lane handoff), 0.52s (full registration),
0.30s (equivalent update), 0.28s (restart), and 0.25s (WAIT_INPUT race). These are
test wall times, not market queue latency samples.

The steady one-symbol fixture measured exactly one `_checkpoint_inputs` call,
on `opening-checkpoint-journal`, one complete preparation, one handoff, and one
five-minute aggregation for all four S0/S1 Call/Put results. Its S0 outcomes remain
INCOMPLETE due to missing cross-day proof; both S1 outcomes are complete research
outcomes. This is TEST_ONLY business evidence, not a natural market signal.

Covered races/boundaries:

- Same-size durable minute edit and appended contradictory minute revision.
- Same-size source file content change.
- Actual clock attachment publication changing the clock identity.
- Real local TEST_ONLY receipt expiry while queued, with no permission renewal.
- Already saved future receive time crossing its legal admission boundary.
- Source update after durable admission but before handoff.
- Source update during computation; old results cannot commit the newer generation.
- Equivalent notification during computation; no stranded LEASED task.
- Data arrival between successful WAIT_INPUT commit and volatile waiting registration.
- Deadline or clock/method boundary changing after precommit validation.
- Restart from an existing leased checkpoint; original deadline unchanged.

Initial new-test iteration was 8 failed / 3 passed. It exposed a proof-path omission
when a rebuilt reference dropped an input-only proof path; the before-set is now
retained in the guard. Other fixture failures came from a real asynchronous history
refresh not yet settled and an incorrect spy argument index. Those failures were
not counted as acceptance. Later focused runs passed; the final 52-case result
above is the affected baseline for integration.

## Exact Changed Runtime/Test Files

All paths below are relative to `delivery-7d/opening-first-hour/`.

| File | SHA-256 |
| --- | --- |
| prepared_generation.py (new) | 22a550e70b4f9615c10b2041a8f667b1ae115147a39b5f064842f86c33c18867 |
| prepared_minutes.py | 56caada6a8eee39242b8d95c332f54afaab64668c16025c74bf65658863a9664 |
| first_hour.py | e117b776fb54ed160d0b90cea3a611b18ff3b6294a2048de057c39dbf47b8840 |
| first_hour_runtime.py | 2b216bb88296bbebcb3f595aa6abc83e007346aa87c5098e06665eb39c08352e |
| first_hour_journal.py | a0988b6ff1cef310c8687bf8701e732673dab0790567b2002307ad3b02b30e88 |
| first_hour_minute_decisions.py | ff6e45fb80923894f628ff6a750db0a870e1c7bb0acfd954a5cf86666a95a749 |
| method_snapshot.py | 525b5cf4060498a41c630fbd03a8ea1c24bc6fd31bc1070d6c08f373002929b2 |
| test_generation_handoff.py (new) | b1ec1879299e527bd41474e806a1757d4f50ae0e1fc37ffd5102dfd3d701ca2f |

Only this B report was added under weekend-20261031. No top-level RESUME, base
workspace, production payload, manifest, approval or business database was edited.

## Integration Boundaries / Remaining Work

1. No topology short or matched hour was run by B, per parent freeze instruction.
   The parent must include the new `prepared_generation.py` in the exact tested
   payload and verify the actual child import paths before topology acceptance.
2. The latest 9.093s queue P95 FAIL remains the last measured topology result.
   Fewer complete preparations are demonstrated, not a <=2s whole-pool latency
   PASS. B adds counters `generation_preparations`, `generation_handoffs`,
   `generation_boundary_checks`, `generation_invalidations`, and timings
   `generation_preparation_seconds` / `generation_validation_seconds`.
3. Durable byte-token reads remain before compute and commit. They avoid parsing
   and reference reconstruction but still incur bounded I/O. Measure their cost
   under the 75900-revision, three-page, eleven-point assembly before attributing
   an end-to-end improvement. No timeout/limit was raised to mask it.
4. This is not an atomic snapshot across SQLite databases and external files.
   Current exact-byte guards, serialized owner notifications and research-journal
   CAS define the boundary. Arbitrary external writes without the existing owner
   notification protocol are not a new supported mutation API.
5. Historical 503/429 attribution, actual HTTP topology, AI/page integration,
   natural input/window evidence and exact release acceptance belong to parent
   integration and remain independently adjudicated. B does not declare them PASS.
6. Real method/budget expiry is not renewed by TEST_ONLY receipts. Recovery,
   permission renewal and exact launch acceptance remain the user's decisions.

Resume pointer: use the eight frozen files above, run parent integrated short
penetration after all owners freeze, preserve the old verdicts, then run the
matching-hour only under the parent's ordered acceptance flow. B has no running
test child or background coding scheduler.
