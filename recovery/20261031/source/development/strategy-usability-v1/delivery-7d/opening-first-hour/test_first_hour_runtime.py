from datetime import date, timedelta
import sqlite3
import time

from kquant import options_one_minute
from first_hour import policies, session_bounds_utc
from first_hour_runtime import TrendLane


class TestOnlyHub:
    __test__ = False

    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


def test_source_notification_preserves_latest_native_reference(tmp_path, monkeypatch):
    from kquant import options_price_reference
    minute = tmp_path/'minute.sqlite3'
    research = tmp_path/'research.sqlite3'
    options_one_minute.initialize(minute)
    reviews = tmp_path/'reviews.json'
    reviews.write_text('{}', encoding='utf-8')
    day = date(2026, 10, 22)
    opening, _ = session_bounds_utc(day)
    lane = TrendLane(minute, TestOnlyHub(), path=research, clock=lambda: opening,
                     source_root=tmp_path, source_reviews_path=reviews)
    calls = []
    monkeypatch.setattr(options_price_reference, 'build',
                        lambda *a, **kw: calls.append(kw) or {'raw_quote': {}})
    try:
        latest = ('CYN', day, [], 'TEST_ONLY', {'raw_quote': {'symbol': 'CYN', 'revision': 2}})
        with lane.lock:
            lane.latest_inputs[('CYN', day)] = latest
            lane.input_epochs[('CYN', day)] = 2
        assert lane.source_facts_ready('CYN', day)
        assert calls == []
        assert lane.latest_inputs[('CYN', day)] == latest
        assert lane.input_epochs[('CYN', day)] == 3
    finally:
        lane.close()


def test_readmission_keeps_original_slot_and_latest_input(tmp_path):
    minute = tmp_path/'minute.sqlite3'
    options_one_minute.initialize(minute)
    reviews = tmp_path/'reviews.json'
    reviews.write_text('{}', encoding='utf-8')
    day = date(2026, 10, 22)
    opening, _ = session_bounds_utc(day)
    lane = TrendLane(minute, TestOnlyHub(), path=tmp_path/'research.sqlite3',
                     clock=lambda: opening, source_root=tmp_path, source_reviews_path=reviews)
    old = ('AI', day, [], 'TEST_ONLY', {'raw_quote': {}})
    new = (*old[:4], {'raw_quote': {'symbol': 'AI', 'currency': 'USD'}})
    key = ('opening_momentum', day.isoformat(), 'AI', 1)
    try:
        # Hold the real condition so the writer cannot consume the asserted item.
        with lane.lock:
            lane.latest_inputs[('AI', day)] = new
            lane._readmit_current(key, old)
            assert lane.incoming[key] == new
            assert list(lane.incoming) == [key]
            lane._readmit_current(key, old)
            assert len(lane.incoming) == 1
            lane.incoming.clear()
    finally:
        lane.close()


def test_actual_constructor_and_background_last_checkpoint(tmp_path):
    minute = tmp_path/'minute'/'minute.sqlite3'
    research = tmp_path/'research'/'research.sqlite3'
    minute.parent.mkdir()
    research.parent.mkdir()
    options_one_minute.initialize(minute)
    reviews = tmp_path/'reviews.json'
    reviews.write_text('{}', encoding='utf-8')
    day = date(2026, 10, 22)
    opening, _ = session_bounds_utc(day)
    now = [opening]
    hub = TestOnlyHub()
    lane = TrendLane(minute, hub, path=research, clock=lambda: now[0],
                     source_root=tmp_path, source_reviews_path=reviews)
    try:
        registered = [{'symbol': 'GWH', 'identity_status': 'verified'}]
        lane.tick_registered(registered, day, 'TEST_ONLY', now[0])
        with sqlite3.connect(research) as db:
            assert db.execute('SELECT count(*) FROM two_hour_jobs').fetchone()[0] == 11
        now[0] = opening+timedelta(minutes=55, seconds=1)
        lane.tick_registered(registered, day, 'TEST_ONLY', now[0])
        timeout = time.monotonic()+8
        found = []
        while time.monotonic() < timeout:
            with sqlite3.connect(research, timeout=.2) as db:
                found = db.execute('SELECT policy_hash,state FROM evaluations').fetchall()
            if len(found) >= 4:
                break
            time.sleep(.05)
        assert len(found) == 4, lane.state
        assert {r[0] for r in found} == {p['policy_hash'] for p in policies().values()}
        assert all(r[1] == 'INCOMPLETE' for r in found)
        assert hub.events
    finally:
        lane.close()
    assert not lane.thread.is_alive()
    assert not lane.writer.is_alive()


def test_compute_reads_decisions_without_reproducing_them(tmp_path, monkeypatch):
    import first_hour_minute_decisions
    minute = tmp_path/'minute.sqlite3'
    research = tmp_path/'research.sqlite3'
    options_one_minute.initialize(minute)
    reviews_path = tmp_path/'reviews.json'
    reviews_path.write_text('{}', encoding='utf-8')
    day = date(2026, 10, 22)
    opening, _ = session_bounds_utc(day)
    now = opening+timedelta(minutes=10, seconds=1)
    produced = []
    monkeypatch.setattr(first_hour_minute_decisions, 'resolve',
                        lambda *args, **kwargs: produced.append(kwargs['symbol']) or [])
    lane = TrendLane(minute, TestOnlyHub(), path=research, clock=lambda: now,
                     source_root=tmp_path, source_reviews_path=reviews_path)
    try:
        key = ('opening_momentum', day.isoformat(), 'AI', 2)
        job = ('AI', day, [], 'TEST_ONLY', {})
        reviews = {'canonical_resolution_method': {'test_only': True}}
        lane._checkpoint_inputs(key, job, now, reviews, rebuild_reference=False, produce_decisions=True)
        _, decisions = lane._checkpoint_inputs(key, job, now, reviews)
        assert produced == ['AI']
        assert decisions == []  # No fabricated decision when the durable store is empty.
    finally:
        lane.close()
