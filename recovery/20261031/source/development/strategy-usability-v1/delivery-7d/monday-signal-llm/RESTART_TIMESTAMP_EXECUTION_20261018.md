# Restart Timestamp Compatibility Execution

Latest2026-10-18T12:57Z. Read this before earlier launch/recovery snapshots.

## Actual State

The user genuinely approved b6cf37cc4955061a, reply
call_84a702a5a149449886c217896fa859ae:0, first observed12:40:51Z. Receipt preserved.
At12:41:24Z the original entry stopped restored d4f4 for that approved replacement.
The new pre-stop metadata/hash verification passed. At12:41:30Z the original
five-role gate rejected ACTIVE_DATABASE_BUSINESS_BASELINE_CHANGED(main); no new
backend/SDK/worker started. Current service is STOPPED, not scanning. Do not
describe restored d4f4's earlier600s as evidence it is still running now.

No business database rollback, timestamp rewrite, reinitialization, copy, WAL
deletion or index removal was performed to evade the guard. Both genuine exact
approvals and both distinct startup rejections remain real evidence.

## Actual Narrow Difference

Read-only evidence/main-baseline-change-20261018.json compares the retained main
snapshot and current main. Original audit39, tasks960 and events2102 prefixes
are byte-equivalent. Tasks now1382/events4879: appended progress is preserved.
Watchlist114/114 rows, no deletion or identity/status/capability change. Only
row31 NVDA updated_at differs:2026-10-04T12:11:23.221605+00:00 ->
2026-10-18T11:30:13.958450+00:00. Normal quote/capability GET producers update this
metadata timestamp even when the recorded available status is unchanged. Actual
prior backend log has NVDA quote/expiry requests. Caller attribution is not
asserted from wall-time overlap, and no provider fault or corruption is inferred.

## Minimal Fix

Two copied modules in metadata-followup/patches/kquant change only restart
comparison. main/stock_watchlist_members may keep a valid forward updated_at up
to60s ahead of current recovery-host time. This is metadata validation, NOT a
VERIFIED_BOUND market-clock claim. All other columns, rowids, prefix counts,
original snapshot prefix hash/file identity and all other business tables stay
strict. Invalid/backward/future timestamps, status/identity changes or deleted
rows still reject. Existing source, qualification, schema and exact OWNER gates
remain. No active database content is rewritten.

Actual read-only main-role comparison now passes this narrow compatibility:
evidence/real-restart-metadata-20261018.json. It is explicitly NOT a full five-role
production launch pass or fake OWNER approval.12 positive/negative helper tests
pass. Actual child-process five-role integration plus existing active-restart
regressions:36passed, evidence/restart-metadata-active-regressions.xml.
Broader legacy run:45passed/3failed; three old launcher assertions expect raw
errors and no lifecycle, whereas current launcher sanitizes errors and persists
preflight lifecycle. Keep evidence/restart-metadata-affected-regressions.xml; do
not silently count those as passed or edit the accepted launcher to leak errors.

## Exact Candidate And In-Flight Evidence

New UNACCEPTED local-candidate-4998d113d64b3570.
Payload c5fc0f8bf80c37b0f981d24855aa9b4fe56db14a5737c8ec0669c874fc6d2052.
Projection65d61ab6d6ee856d3a30a9abf103197e30f3763aacb035fd2fd288a4018c8739.
Only the two restart guard modules differ from b6cf runtime targets; strategy,
source rules, builds, model config and budgets are unchanged. Separate metadata-
tools/bootstrap.py and run_assembly.py preserve older frozen harnesses and verify
the actual two module paths. No __new__/whole-tick replacement.

Short120.031s,258/258 background reads, errors/children empty, source/build matched.
Matching3600s hour RUNNING in session46005, monday-metadata-hour-4998-20261018,
expected end about13:56Z. Freeze metadata payload/metadata-tools/build. Do not
repeat an unchanged hour or edit the selected sources during it. After completion
close_matching_hour.py and prepare_launch_evidence.py for this exact projection.
Use the explicitly scoped apply_stopped_candidate.py attachment, no runtime code edits. Then one exact changed-guard launch
decision, original entry and actual600s observer. Old b6cf approval cannot be
borrowed for new guard code, and original data cycle/login/fee approval is not reasked.

Small archive1192891bytes,SHA256789c9106eab77c78be8e9e7c0d3da89b58b867af6781e69e960d87c39df6537c.
No databases/secrets; cloud upload/redownload not verified. Old payload rollback
cannot currently pass the retained timestamp baseline; do not force it by editing
data. Fixed deadline2026-10-23T14:30:22Z; no real model request while key deferred.

Already-stopped recovery attachment hashcdf859052c48ba5791e810e8af9cda0a04386f49d515fb98db0a48abe591b648:
the prior STOPPED record correctly remains d4f4, selected entry b6cf. Ordinary
Stop would reject mismatch. Attachment requires explicit new OWNER scope/hash,
actual absence of production processes/listeners, same frozen projection/receipt/
archive/hour guards and original startup. Four denial/read-only tests and actual
stopped-state dry-run pass; it changes no runtime payload hashes or business DBs.
