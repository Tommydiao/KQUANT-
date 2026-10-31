"""Late cold boot cannot manufacture the missed opening's journal jobs."""
from datetime import timedelta
import sqlite3
from types import SimpleNamespace

from kquant import options_one_minute as common
from kquant import options_opening_momentum_journal as journal
from kquant.options_opening_trend_runtime import TrendLane
from test_options_opening_momentum import inputs


def test_actual_lane_after_cutoff_keeps_absent_jobs_absent(tmp_path):
    args = inputs()
    minute, research = tmp_path / 'minute/minute.sqlite3', tmp_path / 'research/research.sqlite3'
    minute.parent.mkdir()
    research.parent.mkdir()
    common.initialize(minute)
    now = args['opening'] + timedelta(minutes=31)
    day = args['opening'].astimezone(common.NY).date()
    registered = [{'symbol': args['symbol'], 'identity_status': 'verified'}]
    lane = TrendLane(minute, SimpleNamespace(publish=lambda *a: None), path=research, clock=lambda: now)
    try:
        lane.recover_registered(registered, day, 'TEST_ONLY-scope')
        with sqlite3.connect(research) as db:
            assert db.execute('SELECT COUNT(*) FROM two_hour_jobs').fetchone()[0] == 0
        assert lane.state['checkpoint_recovery'] == 'ENTRY_WINDOW_CLOSED_NO_BACKFILL'
    finally:
        lane.close()


def test_actual_lane_after_cutoff_retains_original_durable_deadlines(tmp_path):
    args = inputs()
    minute, research = tmp_path / 'minute/minute.sqlite3', tmp_path / 'research/research.sqlite3'
    minute.parent.mkdir()
    research.parent.mkdir()
    common.initialize(minute)
    now = args['opening'] + timedelta(minutes=31)
    day = args['opening'].astimezone(common.NY).date()
    registered = [{'symbol': args['symbol'], 'identity_status': 'verified'}]
    lane = TrendLane(minute, SimpleNamespace(publish=lambda *a: None), path=research, clock=lambda: now)
    try:
        journal.register_clock_positions(research, registered, day, 'TEST_ONLY-scope', args['opening'])
        with sqlite3.connect(research) as db:
            original = db.execute('SELECT job_id,deadline_at FROM two_hour_jobs ORDER BY job_id').fetchall()
        assert len(original) == 5
        lane.recover_registered(registered, day, 'TEST_ONLY-scope')
        with sqlite3.connect(research) as db:
            assert db.execute('SELECT job_id,deadline_at FROM two_hour_jobs ORDER BY job_id').fetchall() == original
            assert db.execute("SELECT COUNT(*) FROM two_hour_jobs WHERE state='EXPIRED'").fetchone()[0] == 5
    finally:
        lane.close()
