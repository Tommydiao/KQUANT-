"""Synthetic external transport through actual Worker/recovery/store/journal/model."""
from contextlib import closing
from copy import deepcopy
from datetime import timedelta
import json
import queue
import sqlite3
from time import monotonic, sleep
from types import SimpleNamespace

from kquant import options_one_minute as common
from kquant import options_clock_measurement
from kquant import options_minute_decisions
from kquant.options_one_minute_runtime import OneMinuteResearchWorker
from kquant.options_opening_trend_runtime import TrendLane
from kquant.options_opening_trend_recovery import TrendRecoveryLane
from test_method_binding import PATCH, CONFIG, synthetic_inputs


def test_push_cache_through_worker_pull_durable_wakeup_and_s1(tmp_path, monkeypatch):
    args = synthetic_inputs()
    started = monotonic()
    now = lambda: args['now'] + timedelta(seconds=monotonic()-started)
    minute = tmp_path / 'epoch' / 'minute.sqlite3'
    research = tmp_path / 'research' / 'opening.sqlite3'
    minute.parent.mkdir()
    research.parent.mkdir()
    common.initialize(minute)
    calls, events = [], []

    class Transport:
        def event_queue(self, *unused, **kwargs):
            return queue.Queue()

        def candlesticks(self, provider, period, count, adjustment, timeout):
            calls.append(dict(provider=provider, count=count, requested_at=now().isoformat()))
            return [SimpleNamespace(timestamp=common.timestamp(bar['open_at']),
                **{key: bar[key] for key in ('open', 'high', 'low', 'close')},
                volume=100, turnover=10000) for bar in args['bars'][2:]]

    def measured_fixture():
        return dict(state='VERIFIED_BOUND', uncertainty_ms=50,
            checked_at=(now()-timedelta(seconds=1)).isoformat(),
            source_hash='TEST_ONLY_EXTERNAL_MEASUREMENT_ATTACHMENT', test_only=True)

    monkeypatch.setattr(options_clock_measurement, 'snapshot', measured_fixture)
    monkeypatch.setattr(options_minute_decisions, 'ROOT', PATCH)
    hub = SimpleNamespace(publish=events.append)
    worker = OneMinuteResearchWorker(tmp_path/'unused-main.sqlite3', hub,
        path=minute, runtime=Transport(), clock=now)
    worker.day = args['opening'].date()
    worker.provider_by_symbol = {'TEST_ONLY': 'TEST_ONLY.US'}
    worker.manifest = {'scope_hash': args['scope_hash']}
    worker.trend_references = {'TEST_ONLY': args['reference']}
    lane = TrendLane(minute, hub, path=research, clock=now,
        source_root=PATCH, source_reviews_path=PATCH/CONFIG)
    recovery = TrendRecoveryLane(minute,
        lambda symbol, opened: worker._recover(symbol, opened, snapshot_count=30),
        queue_path=research, clock=now)
    worker.trend_lane, worker.trend_recovery_lane = lane, recovery
    recovery.start()

    def rows():
        with closing(sqlite3.connect(research, timeout=.1)) as db:
            return [json.loads(row[0]) for row in db.execute(
                'SELECT payload_json FROM evaluations WHERE symbol=? ORDER BY rowid', ('TEST_ONLY',))]

    try:
        pushes = deepcopy(args['bars'][2:])
        for row in pushes:
            row['sdk_evidence'] = dict(interface='QuoteContext.set_on_candlestick', adjustment='NOT_PROVIDED')
            worker._record(row)
        until = monotonic()+8
        while monotonic() < until:
            previous = rows()
            if any(row.get('strategy_comparison', {}).get('s1', {}).get('state') == 'INCOMPLETE' for row in previous):
                break
            sleep(.02)
        else:
            raise AssertionError('PUSH_ONLY_INCOMPLETE_NOT_PERSISTED')
        until = monotonic()+10
        final = []
        while monotonic() < until:
            worker._process_trend_recovery(now())
            final = rows()
            if any(row.get('strategy_comparison', {}).get('s1', {}).get('state') == 'NUMERIC_PASS' for row in final):
                break
            sleep(.02)
        else:
            raise AssertionError({'lane': lane.state, 'recovery': recovery.state,
                'calls': calls, 'rows': [(row['state'], row.get('reasons')) for row in final]})
        assert len(calls) == 1
        assert calls[0]['provider'] == 'TEST_ONLY.US' and calls[0]['count'] == 30
        passed = next(row for row in reversed(final)
            if row.get('strategy_comparison', {}).get('s1', {}).get('state') == 'NUMERIC_PASS')
        assert passed['state'] == 'INCOMPLETE'
        assert passed['strategy_comparison']['s1']['deadline_at'] == '2026-10-19T13:40:00+00:00'
        assert not passed['qualified_signal']
        stored = common.stored_bars('TEST_ONLY', '2026-10-19', minute)
        assert len(stored) == 5
        assert all(row['sdk_evidence']['adjustment'] == 'NoAdjust' for row in stored.values())
        assert all(row['sdk_evidence']['clock_evidence']['test_only'] for row in stored.values())
        with closing(sqlite3.connect(research, timeout=.1)) as db:
            job = db.execute("SELECT state,deadline_at,payload_json FROM two_hour_jobs "
                "WHERE json_extract(payload_json,'$.kind')='OPENING_TREND_BAR_RECOVERY'").fetchone()
            assert job[0] == 'DONE' and job[1] == '2026-10-19T13:40:00+00:00'
            generation = db.execute("SELECT payload_json FROM two_hour_jobs "
                "WHERE json_extract(payload_json,'$.kind')='OPENING_MOMENTUM_CALCULATION'").fetchone()
            assert json.loads(generation[0])['input_generation'] >= 2
        assert not minute.with_name('opening_trend_research.sqlite3').exists()
    finally:
        recovery.close()
        lane.close()
        worker.provider_jobs.shutdown(wait=True, cancel_futures=True)
        worker.risk_jobs.shutdown(wait=True, cancel_futures=True)
