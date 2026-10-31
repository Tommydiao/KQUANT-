"""Incident regression: real routes, cache locks, and price-component boundaries."""
from datetime import UTC, datetime, timedelta
from threading import Event
from time import monotonic

import pytest
from fastapi.testclient import TestClient

from kquant.status_snapshot import StatusSnapshot, SnapshotUnavailable
from kquant.research_http_snapshots import ResearchHttpSnapshots
from kquant import options_opening_momentum as model
from test_options_opening_momentum import inputs
from kquant.config import KquantConfig
from kquant.dashboard.app import create_app


def _app(tmp_path):
    return create_app(config=KquantConfig(db_path=tmp_path / 'business.sqlite3',
        outputs_dir=tmp_path / 'outputs'), research_store=tmp_path / 'research.sqlite3',
        manual_store=tmp_path / 'manual.sqlite3')


def test_peek_never_waits_for_loader_or_cache_lock():
    cache = StatusSnapshot(ttl=1)
    gate = Event()
    try:
        assert cache.refresh("day", lambda: gate.wait(2) or {"count": 12})
        started = monotonic()
        for _ in range(100):
            with pytest.raises(SnapshotUnavailable):
                cache.peek("day")
        assert monotonic() - started < .25
        assert not cache.refresh("day", lambda: {"count": 99})
        cache.lock.acquire()
        try:
            with pytest.raises(SnapshotUnavailable, match="BUSY"):
                cache.peek("day")
        finally:
            cache.lock.release()
    finally:
        gate.set()
        cache.close()


def test_partial_price_components_do_not_claim_s0_pass_or_ignore_conflict():
    args = inputs()
    args.pop("right")
    args["reference"] = {"reference_blockers": ["PREVIOUS_CLOSE_UNKNOWN"]}
    rows = model.evaluate_pair(**args)
    for row in rows:
        assert row["state"] == "INCOMPLETE"
        assert row["reasons"] == ["PRICE_REFERENCE_UNVERIFIED"]
        assert row["factor_evidence"]["momentum"] > .5
        assert row["factor_evidence"]["checks"]["daily_direction"] is None
        assert not row["qualified_signal"]
    args["bars"].pop()
    assert "factor_evidence" not in model.evaluate_pair(**args)[0]


def test_real_http_live_and_current_do_not_touch_os_sdk_db_or_worker(tmp_path, monkeypatch):
    app = _app(tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError("GET started slow work")
    monkeypatch.setattr("kquant.options_service_observation.observe", forbidden)
    monkeypatch.setattr("kquant.status_worker.load_current_cards", forbidden)
    monkeypatch.setattr("kquant.status_worker.load_opening_trend", forbidden)
    monkeypatch.setattr(app.state.option_radar_supervisor, "one_minute_worker_status", forbidden)
    client = TestClient(app)
    started = monotonic()
    assert client.get("/api/health/live").status_code == 200
    assert client.get("/api/options/opening-trend/current").status_code == 503
    assert client.get("/api/options/one-minute/status?research_strategy=opening_momentum&compact=true").status_code == 503
    assert monotonic() - started < 1


def test_quote_and_shape_expiration_are_not_renewed_by_snapshot_reads():
    day = datetime.now(UTC).astimezone(__import__('zoneinfo').ZoneInfo("America/New_York")).date().isoformat()
    now = datetime.now(UTC)
    row = {"deadline_at": (now + timedelta(seconds=300)).isoformat(),
           "current_eligibility": {"state": "QUALIFIED", "valid_until": (now - timedelta(seconds=.1)).isoformat()}}
    feed = ResearchHttpSnapshots(lambda: {"session": day, "scope_hash": "scope"},
        lambda *args: {"candidates": [row], "evaluations": [row]}, lambda: {"state": "RUNNING"})
    try:
        feed.tick()
        for cache in feed.caches.values():
            cache.future.result(timeout=2)
        feed.tick()
        result = feed.read("opening_momentum", "current")
        assert result["candidates"] == []
        assert result["evaluations"][0]["current_eligibility"]["state"] == "UNCONFIRMED"
        assert row["current_eligibility"]["valid_until"] == (now - timedelta(seconds=.1)).isoformat()
    finally:
        feed.close()


def test_stuck_background_observer_and_query_leave_live_responsive(tmp_path):
    app = _app(tmp_path)
    feed = app.state.research_http_snapshots
    gate = Event()
    feed.observer = lambda: gate.wait(2) or {"state": "RUNNING"}
    feed.loader = lambda *args: gate.wait(2) or {"candidates": []}
    try:
        feed.tick()
        client = TestClient(app)
        samples = []
        for _ in range(20):
            started = monotonic()
            assert client.get("/api/health/live").status_code == 200
            assert client.get("/api/options/opening-trend/current").status_code == 503
            samples.append(monotonic() - started)
        assert max(samples) < 1
    finally:
        gate.set()
        feed.close()


def test_periodic_snapshot_completion_is_not_a_new_business_event():
    published = []
    day = datetime.now(UTC).astimezone(__import__('zoneinfo').ZoneInfo("America/New_York")).date().isoformat()
    feed = ResearchHttpSnapshots(lambda: {"session": day, "scope_hash": "scope"},
        lambda *args: {"candidates": [], "summary": {"evaluated_directions": 2}},
        lambda: {"state": "RUNNING"}, on_complete=published.append)
    try:
        feed.tick()
        for cache in feed.caches.values():
            cache.future.result(timeout=2)
        feed.tick()
        assert sorted(published) == ['opening_momentum', 'opening_trend']
        for cache in feed.caches.values():
            cache.completed = 0
            cache.attempted = 0
        feed.tick()
        for cache in feed.caches.values():
            if cache.future is not None:
                cache.future.result(timeout=2)
        feed.tick()
        assert sorted(published) == ['opening_momentum', 'opening_trend']
        feed.context_at -= 6
        assert feed.health()["research_worker"]["runtime_health"] == "UNCONFIRMED_STALE"
    finally:
        feed.close()


def test_batch_input_connection_is_reused_but_versions_are_read_again(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from copy import deepcopy
    from threading import local
    from kquant import bounded_sqlite
    from kquant import options_one_minute as common
    from kquant.options_opening_trend_runtime import TrendLane

    args = inputs()
    minute = tmp_path / "minutes.sqlite3"
    common.initialize(minute)
    session = args["opening"].astimezone(common.NY).date()
    common.save_bars(args["bars"], session.isoformat(), minute)
    lane = TrendLane.__new__(TrendLane)
    lane.minute_path = minute
    lane.path = tmp_path / "unopened-research.sqlite3"
    lane.input_read_context = local()
    original = bounded_sqlite.read_connection
    opened = []

    @contextmanager
    def counted(path, **kwargs):
        opened.append(kwargs["seconds"])
        with original(path, **kwargs) as db:
            yield db

    monkeypatch.setattr(bounded_sqlite, "read_connection", counted)
    key = "opening_momentum", session.isoformat(), args["symbol"], 1
    job = args["symbol"], session, [], "scope", {}
    with lane._input_batch():
        first, _ = lane._checkpoint_inputs(key, job, args["now"], {})
        changed = deepcopy(args["bars"][0])
        changed["close"] -= .01
        common.save_bars([changed], session.isoformat(), minute)
        second, _ = lane._checkpoint_inputs(key, job, args["now"], {})
        assert len(second[2]) == len(first[2]) + 1
        assert common.digest(first[2]) != common.digest(second[2])
    assert opened == [.3]
    assert lane.input_read_context.connection is None


def test_compact_budget_includes_attached_health_and_retains_current_channel():
    import json
    day = datetime.now(UTC).astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")).date().isoformat()
    rows = [{"evaluation_id": str(index), "summary_text": "x" * 10000} for index in range(10)]
    feed = ResearchHttpSnapshots(lambda: {"session": day, "scope_hash": "scope"},
        lambda *args: {"evaluations": rows, "candidates": [], "summary": {"evaluated_directions": 200}},
        lambda: {"state": "RUNNING"})
    try:
        feed.tick()
        for cache in feed.caches.values():
            cache.future.result(timeout=2)
        feed.tick()
        compact = feed.read("opening_momentum", "compact")
        assert len(json.dumps(compact, ensure_ascii=False).encode()) <= 32768
        assert compact["evaluations_total"] == 10 and compact["evaluations_deferred"]
        assert compact["summary"]["evaluated_directions"] == 200
        assert len(feed.read("opening_momentum", "current")["evaluations"]) == 10
        assert len(rows) == 10
    finally:
        feed.close()
