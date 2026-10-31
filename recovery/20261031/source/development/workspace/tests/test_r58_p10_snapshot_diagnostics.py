"""Repeated known faults remain visible without flooding the worker's log pipe."""
from concurrent.futures import Future

from kquant import status_snapshot as snapshots
from kquant.status_worker import StatusQueryFailure


def fail(cache, detail):
    future = Future()
    future.set_exception(StatusQueryFailure(detail))
    cache.future = future
    cache._collect()


def test_duplicate_logs_bounded_but_latest_diagnostic_retained(monkeypatch, caplog):
    clock = [100.0]
    monkeypatch.setattr(snapshots, "monotonic", lambda: clock[0])
    cache = snapshots.StatusSnapshot()
    try:
        detail = {"code": "POLICY_CONFIG_MISSING", "phase": "policy",
                  "error_type": "FileNotFoundError", "elapsed_ms": 0}
        fail(cache, detail)
        fail(cache, {**detail, "elapsed_ms": 16})
        assert len(caplog.records) == 1
        assert cache.error_detail["elapsed_ms"] == 16
        clock[0] += 60
        fail(cache, detail)
        assert len(caplog.records) == 2
        fail(cache, {**detail, "code": "DATABASE_LOCKED"})
        assert len(caplog.records) == 3
    finally:
        cache.close()


def test_recovery_resets_fault_log_and_read_only_stale_evidence(monkeypatch, caplog):
    monkeypatch.setattr(snapshots, "monotonic", lambda: 100.0)
    cache = snapshots.StatusSnapshot()
    cache.value, cache.cache_key = {"quote_received_at": "original"}, "session"
    cache.cache_generation = 0
    try:
        detail = {"code": "POLICY_CONFIG_MISSING", "phase": "policy"}
        fail(cache, detail)
        assert cache.peek("session")["snapshot"]["state"] == "STALE"
        assert cache.peek("session")["quote_received_at"] == "original"
        future = Future()
        future.set_result({"quote_received_at": "new-evidence"})
        cache.future, cache.pending_key = future, "session"
        cache.pending_started, cache.started_at = 100.0, "TEST_ONLY-as-of"
        cache._collect()
        assert cache.peek("session")["snapshot"]["error_detail"] is None
        fail(cache, detail)
        assert len(caplog.records) == 2
        assert cache.peek("session")["snapshot"]["state"] == "STALE"
    finally:
        cache.close()
