"""Real recovery queue with synthetic native pulls around a measured boundary."""
from contextlib import closing
from copy import deepcopy
from datetime import timedelta
import sqlite3
import pytest

from kquant import options_one_minute as common
from kquant import options_minute_decisions as decisions
from kquant.options_opening_trend_recovery import TrendRecoveryLane
from kquant.options_opening_momentum import load_policy
from test_method_binding import synthetic_inputs


def pulled_rows(args, milliseconds):
    requested = args['checkpoint'] + timedelta(milliseconds=milliseconds)
    received = requested + timedelta(milliseconds=20)
    rows = deepcopy(args['bars'][2:])
    for row in rows:
        row.update(request_started_at=requested.isoformat(), received_at=received.isoformat())
        row['sdk_evidence'] = dict(provider_symbol='TEST_ONLY.US', interface='QuoteContext.candlesticks',
            adjustment='NoAdjust', request_started_at=requested.isoformat(),
            clock_evidence=dict(state='VERIFIED_BOUND', uncertainty_ms=50,
                checked_at=(args['checkpoint']-timedelta(seconds=1)).isoformat(), source_hash='TEST_ONLY'))
    return rows, received


@pytest.mark.parametrize('milliseconds,expected', [(20, False), (50, True), (70, True)])
def test_recovery_and_adoption_share_claimed_clock_boundary(tmp_path, milliseconds, expected):
    args = synthetic_inputs()
    rows, now = pulled_rows(args, milliseconds)
    lane = TrendRecoveryLane(tmp_path/'minutes.sqlite3', lambda *a: None,
        queue_path=tmp_path/'research.sqlite3', clock=lambda: now)
    try:
        target = args['checkpoint']-timedelta(minutes=1)
        assert lane.bar_ready('TEST_ONLY', target, rows[-1]) is expected
        assert decisions._local_candidate(rows[-1], {'method': decisions.LOCAL_METHOD}) is expected
        task = lane.task('TEST_ONLY', target,
            {common.timestamp(row['open_at']): row for row in rows}, load_policy(), args['scope_hash'])
        assert (task is None) is expected
    finally:
        lane.close()


def test_early_native_cache_does_not_complete_or_skip_required_pull(tmp_path):
    args = synthetic_inputs()
    rows, now = pulled_rows(args, 20)
    minute, research = tmp_path/'minutes.sqlite3', tmp_path/'research.sqlite3'
    common.initialize(minute)
    common.save_bars(rows, '2026-10-19', minute)
    calls = []
    later, later_received = pulled_rows(args, 70)
    def transport(symbol, opened):
        calls.append((symbol, opened))
        return {'status': 'RECOVERED', 'bars': later}
    lane = TrendRecoveryLane(minute, transport, queue_path=research, clock=lambda: now)
    try:
        p = load_policy()
        task = lane.task('TEST_ONLY', args['checkpoint']-timedelta(minutes=1),
            {common.timestamp(row['open_at']): row for row in rows}, p, args['scope_hash'])
        assert task is not None
        job, _ = lane._cycle({'TEST_ONLY_JOB': task}, None, '2026-10-19', p, args['scope_hash'], False)
        assert job and job['state'] == 'PENDING'
        fetched = lane._fetch(job)
        assert len(calls) == 1
        now = later_received
        lane._cycle({}, (job, fetched), '2026-10-19', p, args['scope_hash'], False)
        with closing(sqlite3.connect(research)) as db:
            state, deadline = db.execute('SELECT state,deadline_at FROM two_hour_jobs WHERE job_id=?',
                ('TEST_ONLY_JOB',)).fetchone()
        assert state == 'DONE'
        assert deadline == '2026-10-19T13:40:00+00:00'
    finally:
        lane.close()
