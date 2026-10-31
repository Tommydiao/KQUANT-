# Weekend AI Sidecar Integration

Scope: bounded A-line store/worker delta. No BASE edits, live database writes,
credential inspection, network calls, front-end edits, topology run or release.
The historical seven-day FAIL remains unchanged. This is not real API acceptance.

## Changed Files

- `patches/kquant/options_research_ai_store.py`: mechanically copied BASE first;
  versioned outbox identity, matching reservation recovery, atomic one-Astra-per-event
  guard across generations, leased-state completion CAS, safe read-side summaries.
- `patches/kquant/options_research_ai_worker.py`: mechanically copied BASE first;
  real first-hour policy IDs, per-cycle config/receipt/expiry gate, pre-request event
  reread, result revalidation, bounded credential probe failures, no default-store
  page-enrichment calls during worker rechecks.
- `test_weekend_sidecar.py`: actual worker constructor/thread, original temporary
  SQLite schemas, explicit TEST_ONLY model clients; all network methods forbidden.

## Client Contract

Worker captures `event['_ai_versions'] = version_identity(config)` before enqueue.
The explicit fields are `prompt_version`, `tools_version`, and `config_hash`.
New production worker configurations require prompt/tools versions; missing version
material is not silently promoted. Legacy stored tasks remain readable but cannot
be claimed under a mismatched new version.

Pure store identity matches main `task_identity(event, role, config)` exactly:

```python
generation = [event['event_id'], event.get('evaluation_id'), event.get('runtime_inputs'),
              event.get('input_revision'),
              (event.get('reference_contract') or {}).get('contract_id')]
work_id = 'opening-ai:' + digest([generation, MODELS[role], event['_ai_versions']])
```

The persisted `scan_id` is the same ID for versioned tasks. Legacy tasks retain the
old packet-based scan ID. Sent or already-reserved work is deferred for budget
reconciliation after process loss, never silently repurchased. Only a lease with
no reservation can requeue automatically. Client reservation checks remain the
authoritative atomic monetary boundary.

Quote refreshes do not create another task. New prompt/tools/config/input versions
can create new Sol work, subject to the shared client task budget. The outbox checks
both existing Astra work and existing Astra reservations in one BEGIN IMMEDIATE
transaction. The client must retain `role_candidate_limit=1` and shared candidate
task budget across all model roles.

The actual 11-point IDs are obtained from `first_hour.policies()`; the integrated
candidate must make `opening-first-hour` importable, as its existing runtime does.
Legacy IDs remain supported. A comparison S1 whose reference owner is S0 is not
enqueued again; the existing page already falls back from S1 AI to row/S0 AI.

## Parent Integration Required

The existing authenticated Astra POST handler still needs a minimal candidate-only
update by the parent integration owner:

1. After its existing authorization check, call
   `captured_event(original, revision, versions=version_identity(ai_config))`.
2. When the selected S1 uses `reference_collection_owner == 'S0'`, read its
   `parent_evaluation_id` and request the owning S0 review. Do not mint another
   cross-variant task or infer an approval.
3. Keep receipt/config checks and user-requested role restriction. The new weekend
   test receipt does not permit production paid work. Unversioned POST work is
   safely deferred as `AI_CONFIGURATION_CHANGED`, not executed under new settings.

Do not hot-edit the existing BASE handler. No extra schema/table or database is
needed for these sidecar changes.

## Read-Side Fields

`summaries()` never imports the paid client. It exposes requested_model,
actual_model/returned_model, elapsed_seconds, endpoint, versions, sanitized response
IDs and token-count usage, original deadline, review timestamp, queue state and
deferred reason. It never exports response items, reasoning text or arbitrary
usage strings. `review_state` is AI_PENDING / COMPLETE / UNAVAILABLE / STALE.
An inaccessible Astra result remains under `astra_review`; it does not overwrite
an existing Sol result. All views keep qualified_signal false.

## Verification

Run from BASE, using the root `.venv` interpreter, without a topology run:

```powershell
& 'E:\kquant 1007\KQUANT-Resume-Latest\.venv\Scripts\python.exe' -m pytest `
  '..\strategy-usability-v1\delivery-7d\weekend-20261031\test_weekend_sidecar.py' `
  '..\strategy-usability-v1\delivery-7d\weekend-20261031\test_weekend_ai.py' -q
```

Result: 30 passed in 6.37 seconds (20 sidecar, 10 main-client tests).
Evidence: `evidence/sidecar-client-tests.xml`.
The initial 16-pass/1-fail run is retained in `evidence/sidecar-tests.xml`;
it exposed withdrawal being reported as generic INPUT_REVISED. The worker now
preserves explicit WITHDRAWN classification while retaining audit-only behavior.

Covered: exact client/store identity, quote dedup, prompt/tool version changes,
sent/unsent reservation recovery, completion CAS, concurrent Astra generations,
existing budget guards, all 11 checkpoint envelopes with actual policy IDs,
real worker construction/restart, asynchronous model barriers, withdrawal,
deadline/quote age, authorization expiry/revocation, missing key, bounded probe
exceptions/401, safe metadata and independent Astra failure.

These are isolated synthetic business fixtures, not natural signals, actual API
success, an 11-point wall-clock acceptance or browser evidence. The parent owns
actual page integration, real capability evidence and final frozen assembly.

## Handoff Hashes

- store: `e35ef28899753bf54917bfb5eb1cbe582e31cb3d19e400ad6ed277e16bd64f6c`
- worker: `bc5a34de4c05045c6d96d7ab0a6b040bb57787d835f9c5ec9a61e7746a44f784`
- tests: `a09ac2922408931022596f3829861964c8173271b28b2e2a4521875419695766`
- combined XML: `f329dbbbfa8c16af6b1f3e79822af75fb6f4d9ad9e01569d0da49456c69435c2`

All test processes finished. No background coding or production activation was
scheduled by this workstream. Resume with the parent integration points above.
