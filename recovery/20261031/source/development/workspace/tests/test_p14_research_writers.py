"""Small qualification expirations share the actual checkpoint writer gate."""
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
import json
import sqlite3
from threading import RLock
from time import sleep
from types import SimpleNamespace

from kquant import options_opening_trend_jobs as jobs
from kquant import options_opening_trend_store as store
from kquant.options_opening_trend_pipeline import QualificationLane

NOW = datetime(2026, 10, 14, 13, 45, tzinfo=UTC)

def seed(path, count):
    store.initialize(path)
    rows = [dict(evaluation_id=str(i), policy_hash='TEST_ONLY', session='2026-10-14',
        symbol='TEST'+str(i), right='CALL', evaluated_at=(NOW-timedelta(minutes=6)).isoformat(),
        state='NUMERIC_PASS', deadline_at=(NOW-timedelta(seconds=1)).isoformat(),
        event_id='TEST_ONLY-'+str(i), scope_hash='TEST_ONLY') for i in range(count)]
    store.persist(rows, path)

def test_expirations_are_bounded_and_original_deadlines_unchanged(tmp_path):
    path = tmp_path/'research.sqlite3'
    seed(path, 19)
    with closing(sqlite3.connect(path)) as db:
        before=dict(db.execute('SELECT evaluation_id,deadline_at FROM qualification_jobs'))
    for expected in (8, 16, 19):
        assert jobs.claim(path, now=NOW) is None
        with closing(sqlite3.connect(path)) as db:
            assert db.execute("SELECT COUNT(*) FROM qualification_jobs WHERE state='EXPIRED'").fetchone()[0]==expected
            assert dict(db.execute('SELECT evaluation_id,deadline_at FROM qualification_jobs'))==before
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT COUNT(*) FROM revisions').fetchone()[0]==19
    assert jobs.claim(path, now=NOW) is None

def test_real_qualification_loop_uses_shared_guard_and_cleans_up(tmp_path, monkeypatch):
    path=tmp_path/'research.sqlite3'
    seed(path, 19)
    lock=RLock()
    calls=[]
    active=[]
    original=jobs.claim
    @contextmanager
    def guard():
        with lock:
            active.append(True)
            calls.append('guard')
            try:yield
            finally:active.pop()
    def claim(*args, **kwargs):
        assert active
        return original(*args, **kwargs)
    monkeypatch.setattr(jobs, 'claim', claim)
    lane=QualificationLane(tmp_path/'unused-main.sqlite3',path,
        SimpleNamespace(publish=lambda event:None),clock=lambda:NOW,
        services=SimpleNamespace(),write_guard=guard)
    try:
        sleep(1.3)
    finally:lane.close()
    assert calls and not lane.thread.is_alive()
    assert lane.state.get('error') is None
    assert not (tmp_path/'unused-main.sqlite3').exists()
