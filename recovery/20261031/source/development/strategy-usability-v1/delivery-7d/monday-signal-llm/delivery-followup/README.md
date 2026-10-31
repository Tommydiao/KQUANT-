# Nested Snapshot Delivery Boundary

This one-module fix is independent of frozen596f's running hour; do not edit that
payload or borrow its hour for the changed hash.

Actual pump tests reproduced two missed notifications: a late AI assessment and
a nested S1 reference revision were present in the fresh background snapshot but
excluded from its publication watermark. A pre-refresh event alone cannot prove
the browser sees the post-refresh data. The original failures are retained in
../evidence/snapshot-ai-before.xml.

The fix includes bounded nested research/reference/cost/outcome and AI material
in the existing publication watermark. It does not move business work into GET,
increase polling/workers/timeouts, alter expiry, create stores or modify strategy.
Only changed material emits the existing snapshot-ready event after collection.

Actual compiled browser baseline timed out after8s without a late snapshot-ready
update. With the fix, an explicitly TEST_ONLY result arrived via real API/Gateway/
SSE and appeared887.33ms after the test completion request, one snapshot event,
zero navigations/manual reloads. Eight desktop variants and disconnect/reconnect
also passed. These are synthetic result/source inputs, not a real model, quote,
market or production delivery/P95 claim. Paths:
../evidence/late-ai-browser-20261018-093328 (baseline failure),
../evidence/late-ai-browser-20261018-093402 (fixed actual browser).

Full affected regression result is90 passed. Final candidate868ede9e22516b3e has
this exact source hash and retains the paired builds unchanged. Its exact actual
loader, short and matched hour must run after596f's already-running hour ends.
No feature expansion is required; this closes the existing page-delivery goal.
