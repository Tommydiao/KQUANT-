from datetime import UTC, datetime
from time import monotonic
from zoneinfo import ZoneInfo

import pytest

from kquant.research_http_snapshots import ResearchHttpSnapshots
from kquant.status_snapshot import SnapshotUnavailable


def make_feed(availability, calls):
    day = datetime.now(UTC).astimezone(ZoneInfo("America/New_York")).date().isoformat()
    def load(strategy, kind, worker):
        calls.append((strategy, kind))
        return {"session": day, "candidates": [], "evaluations": [], "summary": {"evaluated_directions": 2}}
    return ResearchHttpSnapshots(lambda: {"session": day, "scope_hash": "scope"}, load,
                                 lambda: {"state": "RUNNING"}, strategy_availability=availability)


def settle(feed):
    feed.tick()
    for cache in feed.caches.values():
        if cache.future is not None:
            cache.future.result(timeout=2)
    feed.tick()


def test_missing_old_comparison_never_starts_query_and_s0_still_loads():
    calls = []
    feed = make_feed(lambda strategy: {"enabled": strategy == "opening_momentum", "reason": "POLICY_CONFIG_MISSING"}, calls)
    try:
        settle(feed)
        for _ in range(50):
            feed.tick()
        assert calls and all(strategy == "opening_momentum" for strategy, _ in calls)
        assert feed.read("opening_momentum", "current")["session"]
        with pytest.raises(SnapshotUnavailable, match="POLICY_CONFIG_MISSING"):
            feed.read("opening_trend", "current")
        assert all(task["unavailable_reason"] == "POLICY_CONFIG_MISSING" for task in
                   feed.task_observation["tasks"] if task["strategy"] == "opening_trend")
    finally:
        feed.close()


def test_availability_failure_is_per_strategy_not_global():
    calls = []
    def availability(strategy):
        if strategy == "opening_trend":
            raise OSError("missing original")
        return {"enabled": True}
    feed = make_feed(availability, calls)
    try:
        settle(feed)
        assert feed.read("opening_momentum", "current")["session"]
        assert feed.error_type is None
        with pytest.raises(SnapshotUnavailable, match="UNCONFIRMED"):
            feed.read("opening_trend", "compact")
    finally:
        feed.close()


def test_read_uses_memory_not_availability_filesystem_callback():
    calls = []
    feed = make_feed(lambda strategy: {"enabled": True}, calls)
    try:
        settle(feed)
        def forbidden(strategy):
            raise AssertionError("HTTP checked filesystem")
        feed.strategy_availability = forbidden
        started = monotonic()
        assert feed.read("opening_momentum", "current")["session"]
        assert monotonic() - started < .25
    finally:
        feed.close()


def test_removed_policy_hides_retained_snapshot_and_restored_policy_resumes():
    calls = []
    enabled = {"value": True}
    feed = make_feed(lambda strategy: {"enabled": enabled["value"], "reason": "POLICY_CONFIG_MISSING"}, calls)
    try:
        settle(feed)
        assert feed.read("opening_momentum", "current")["session"]
        enabled["value"] = False
        feed.tick()
        with pytest.raises(SnapshotUnavailable, match="POLICY_CONFIG_MISSING"):
            feed.read("opening_momentum", "current")
        enabled["value"] = True
        settle(feed)
        assert feed.read("opening_momentum", "current")["session"]
    finally:
        feed.close()
