from threading import Event

import pytest

from kquant.status_snapshot import StatusSnapshot, SnapshotUnavailable


def test_slow_query_completion_does_not_renew_freshness(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("kquant.status_snapshot.monotonic", lambda: clock[0])
    cache = StatusSnapshot(ttl=5, wait_seconds=1)
    def load():
        clock[0] = 110.0
        return {"count": 12}
    try:
        result = cache.read("day", load)
        assert result["snapshot"]["state"] == "STALE"
        assert cache.completed == 100.0
    finally:
        cache.close()


def test_slow_reads_coalesce_without_fake_zero_or_cross_session_cache():
    cache = StatusSnapshot(wait_seconds=0.001)
    entered, release = Event(), Event()
    calls = []
    def load():
        calls.append(1)
        entered.set()
        release.wait(3)
        return {"count": 12}
    try:
        with pytest.raises(SnapshotUnavailable):
            cache.read("day1", load)
        assert entered.wait(1)
        for _ in range(5):
            with pytest.raises(SnapshotUnavailable):
                cache.read("day1", load)
        assert len(calls) == 1
        release.set()
        cache.future.result(timeout=2)
        assert cache.read("day1", load)["count"] == 12
        release.clear()
        with pytest.raises(SnapshotUnavailable):
            cache.read("day2", load)
    finally:
        release.set()
        cache.pool.shutdown(wait=True)


def test_failure_preserves_stale_data_and_does_not_mutate_cache():
    cache = StatusSnapshot(ttl=0, wait_seconds=1)
    try:
        result = cache.read("day", lambda: {"nested": {"count": 12}})
        result["nested"]["count"] = 0
        def fail():
            raise ValueError("private details should not be returned")
        stale = cache.read("day", fail)
        assert stale["nested"]["count"] == 12
        assert stale["snapshot"]["state"] == "STALE"
        assert stale["snapshot"]["error_type"] == "ValueError"
    finally:
        cache.close()


def test_invalidation_refreshes_before_ttl_without_renewing_field_time():
    cache = StatusSnapshot(ttl=3, wait_seconds=1)
    calls = []
    def load():
        calls.append(1)
        return {"count": len(calls), "bbo_received_at": "original-time"}
    try:
        assert cache.read("day", load)["count"] == 1
        cache.invalidate()
        result = cache.read("day", load)
        assert result["count"] == 2
        assert result["snapshot"]["state"] == "FRESH"
        assert result["bbo_received_at"] == "original-time"
    finally:
        cache.close()


def test_invalidation_during_read_discards_old_result_and_keeps_single_flight():
    cache = StatusSnapshot(ttl=3, wait_seconds=.001)
    entered, release = Event(), Event()
    calls = []
    def load():
        calls.append(1)
        if len(calls) == 2:
            entered.set()
            release.wait(3)
            return {"count": 99}
        return {"count": len(calls)}
    try:
        assert cache.read("day", load)["count"] == 1
        cache.invalidate()
        assert cache.read("day", load)["snapshot"]["state"] == "STALE"
        assert entered.wait(1)
        for _ in range(5):
            cache.invalidate()
            result = cache.read("day", load)
            assert result["count"] == 1 and result["snapshot"]["state"] == "STALE"
        assert len(calls) == 2
        release.set()
        cache.future.result(timeout=2)
        cache.wait_seconds = 1
        result = cache.read("day", load)
        assert result["count"] == 3 and result["snapshot"]["state"] == "FRESH"
    finally:
        release.set()
        cache.pool.shutdown(wait=True)


def test_progress_snapshot_retains_completed_read_as_stale_during_continuous_updates():
    cache = StatusSnapshot(ttl=3, wait_seconds=1, retain_invalidated=True)
    calls = []

    def load():
        calls.append(1)
        cache.invalidate()
        return {"count": len(calls), "received_at": "original"}

    try:
        first = cache.read("day", load)
        second = cache.read("day", load)
        assert second["count"] > first["count"]
        assert second["snapshot"]["state"] == "STALE"
        assert second["received_at"] == "original"
        assert len(calls) <= 4
    finally:
        cache.close()


def test_failed_refresh_retains_safe_diagnostics_and_success_clears_them():
    from kquant.status_worker import StatusQueryFailure
    cache = StatusSnapshot(ttl=0, wait_seconds=1)
    try:
        cache.read("day", lambda: {"original_at": "preserved"})
        def failed():
            raise StatusQueryFailure({"code": "DATABASE_LOCKED", "phase": "latest_status"})
        stale = cache.read("day", failed)
        assert stale["original_at"] == "preserved"
        assert stale["snapshot"]["state"] == "STALE"
        assert stale["snapshot"]["error_detail"]["code"] == "DATABASE_LOCKED"
        recovered = cache.read("day", lambda: {"original_at": "new"})
        assert recovered["snapshot"]["error_detail"] is None
    finally:
        cache.close()


def test_background_completion_notifies_without_a_second_poll():
    entered, release, notified = Event(), Event(), Event()
    cache = StatusSnapshot(wait_seconds=.001, on_complete=notified.set)

    def load():
        entered.set()
        release.wait(2)
        return {"count": 12}

    try:
        with pytest.raises(SnapshotUnavailable):
            cache.read("day", load)
        assert entered.wait(1)
        assert not notified.is_set()
        release.set()
        assert notified.wait(2)
        assert cache.read("day", load)["snapshot"]["state"] == "FRESH"
    finally:
        release.set()
        cache.close()
