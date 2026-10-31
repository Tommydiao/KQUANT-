from concurrent.futures import Future
import importlib.util
from pathlib import Path
import pytest
from kquant.status_snapshot import SnapshotUnavailable

spec = importlib.util.spec_from_file_location(
    "kquant.published_candidate", Path(__file__).with_name("published_status_snapshot.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def publish(cache, value=None, failure=None):
    from time import monotonic
    cache.pending_key = ("2026-10-22", "scope")
    cache.pending_generation = cache.generation
    cache.pending_started = monotonic()
    cache.started_at = "original-time"
    cache.future = Future()
    if failure:
        cache.future.set_exception(failure)
    else:
        cache.future.set_result(value or {"candidates": [{"deadline_at": "original-deadline"}]})
    with cache.lock:
        cache._collect()


def test_read_under_writer_lock_and_detached_result():
    cache = module.PublishedStatusSnapshot()
    try:
        publish(cache)
        with cache.lock:
            result = cache.peek(("2026-10-22", "scope"))
        assert result["snapshot"]["state"] == "FRESH"
        result["candidates"].clear()
        assert len(cache.peek(("2026-10-22", "scope"))["candidates"]) == 1
    finally:
        cache.close()


def test_invalidation_expiry_failure_and_wrong_day():
    cache = module.PublishedStatusSnapshot(retain_invalidated=True)
    try:
        with pytest.raises(SnapshotUnavailable):
            cache.peek(("2026-10-22", "scope"))
        publish(cache)
        cache.invalidate()
        assert cache.peek(("2026-10-22", "scope"))["snapshot"]["state"] == "STALE"
        publish(cache, failure=RuntimeError("test-only"))
        assert cache.peek(("2026-10-22", "scope"))["snapshot"]["error_type"] == "RuntimeError"
        publish(cache)
        cache.ttl = 0
        assert cache.peek(("2026-10-22", "scope"))["snapshot"]["state"] == "STALE"
        with pytest.raises(SnapshotUnavailable):
            cache.peek(("2026-10-23", "scope"))
    finally:
        cache.close()
