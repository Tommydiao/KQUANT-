"""Real producer commits and real Lane CAS, with TEST_ONLY scheduling barriers."""
from datetime import timedelta
import importlib
import json
from pathlib import Path
import sqlite3
import sys
import threading
import time

import pytest

import first_hour_journal as journal
import first_hour_minute_decisions as decisions
from kquant import options_one_minute as common
from kquant import options_price_action_source as actions
from kquant import options_price_facts as facts
from kquant.options_input_commit_fence import commit_fence, require_fence
from test_generation_handoff import actual_lane, dispatch, results, until


def writer(kind, lane, job, bars, now, root):
    if kind == 'minute':
        return lambda: common.save_bar({**bars[-1], 'close': 103,
            'received_at': now.isoformat()}, job[1].isoformat(), lane.minute_path)
    if kind == 'decision':
        value = dict(symbol=job[0], session=job[1].isoformat(), open_at=bars[-1]['open_at'],
            known_at=now.isoformat(), state='TEST_ONLY_UNRESOLVED')
        return lambda: decisions.append_many(lane.path, [value])
    if kind == 'fact':
        value = dict(symbol=job[0], session=job[1].isoformat(),
            known_at=now.isoformat(), valid_until=(now+timedelta(seconds=90)).isoformat())
        value['instrument'] = {k: v for k, v in value.items() if k != 'session'}
        value['status'] = 'TEST_ONLY_UNVERIFIED'
        return lambda: facts.persist_bindings(lane.path, [value])
    index = root/'TEST_ONLY-action-index.json'
    claim = dict(lease_id='TEST_ONLY', target_session=job[1].isoformat(),
                 lease_until=(now+timedelta(seconds=90)).isoformat())
    index.write_text(json.dumps({'records': {job[0]: dict(claim)}}))
    observation = dict(target_session=job[1].isoformat(), status='TEST_ONLY',
        received_at=now.isoformat(), retry_after=None, observation_id='TEST_ONLY',
        coverage_fact={'complete': False, 'test_only': True})
    return lambda: actions.commit_action(index, job[0], claim, observation,
        root/'TEST_ONLY-raw.json', root, job[1], 0, now)


@pytest.mark.parametrize('kind', ['minute', 'decision', 'fact', 'action'])
def test_committed_writer_before_notification_rejects_old_generation(tmp_path, monkeypatch, kind):
    with actual_lane(tmp_path) as (lane, _, now, key, job, bars, _):
        calculated, resume_compute = threading.Event(), threading.Event()
        committed, notify = threading.Event(), threading.Event()
        errors, old_generation = [], []
        original = lane._calculate
        def blocked_calculate(*args, **kwargs):
            value = original(*args, **kwargs)
            if not calculated.is_set():
                old_generation.append(args[4].generation)
                calculated.set()
                assert resume_compute.wait(4)
            return value
        monkeypatch.setattr(lane, '_calculate', blocked_calculate)
        write = writer(kind, lane, job, bars, now[0], tmp_path)
        def producer():
            try:
                write()  # Actual commit, not a mocked SQL operation.
                committed.set()
                assert notify.wait(4)
                lane.source_facts_ready(job[0], job[1])
            except BaseException as exc:
                errors.append(exc)
        dispatch(lane, key, job)
        thread = threading.Thread(target=producer, name='TEST_ONLY-real-input-writer')
        try:
            assert calculated.wait(4), lane.state
            thread.start()
            assert committed.wait(4), errors
            resume_compute.set()
            until(lambda: bool(results(lane.path)))
            assert not notify.is_set()
            assert all(row['runtime_inputs']['input_generation'] > old_generation[0]
                       for row in results(lane.path))
            assert lane.state['generation_invalidations'] >= 1
        finally:
            resume_compute.set()
            notify.set()
            if thread.ident:
                thread.join(4)
        assert not thread.is_alive() and not errors


@pytest.mark.parametrize('kind', ['minute', 'decision', 'fact', 'action'])
def test_writer_cannot_commit_between_final_validation_and_cas(tmp_path, monkeypatch, kind):
    with actual_lane(tmp_path) as (lane, _, now, key, job, bars, _):
        at_cas, release_cas = threading.Event(), threading.Event()
        original = journal.finish_many
        def blocked_cas(*args, **kwargs):
            require_fence()
            if not at_cas.is_set():
                at_cas.set()
                assert release_cas.wait(4)
            return original(*args, **kwargs)
        monkeypatch.setattr(journal, 'finish_many', blocked_cas)
        write = writer(kind, lane, job, bars, now[0], tmp_path)
        dispatch(lane, key, job)
        try:
            assert at_cas.wait(4), lane.state
            started = time.monotonic()
            with pytest.raises(TimeoutError, match='INPUT_COMMIT_FENCE_BUSY'):
                write()
            assert time.monotonic()-started < .5  # Scheduling allowance, acquisition is .05.
            with sqlite3.connect(lane.minute_path) as db:
                assert db.execute('SELECT count(*) FROM one_minute_bars').fetchone()[0] == 5
            with sqlite3.connect(lane.path) as db:
                assert db.execute("SELECT count(*) FROM two_hour_jobs WHERE state='COMPLETED'").fetchone()[0] == 0
            assert not (tmp_path/'work/option_foundation/price-action-facts/AI'/f'{job[1]}.json').exists()
        finally:
            release_cas.set()
        until(lambda: len(results(lane.path)) == 4)
        write()  # Owner may retry unchanged input after the finite busy outcome.


def test_fence_has_one_qualified_identity_and_transaction_owner_required():
    module = importlib.import_module('kquant.options_input_commit_fence')
    assert Path(module.__file__).parent.name == 'kquant'
    assert 'weekend-20261031' in str(module.__file__)
    assert 'options_input_commit_fence' not in sys.modules
    assert 'input_commit_fence' not in sys.modules
    with pytest.raises(RuntimeError, match='REQUIRES_OUTER'):
        facts.persist_prepared_in_transaction(None, {})
    with commit_fence(), commit_fence():
        require_fence()


def test_actual_worker_drain_retains_dequeued_raw_event_on_busy(tmp_path):
    from types import SimpleNamespace
    from longbridge.openapi import Period
    with actual_lane(tmp_path) as (lane, worker, now, key, job, bars, _):
        worker.mapping = {'AI.US': 'AI'}
        candle = SimpleNamespace(timestamp=common.timestamp(bars[-1]['open_at']),
            open=104, high=106, low=103, close=105, volume=1000, turnover=100000)
        event = SimpleNamespace(is_confirmed=True, period=Period.Min_1, candlestick=candle)
        item = ('candle', 'AI.US', event, now[0].isoformat())
        worker.sink.put(item)
        worker.sink.put(('ignored', 'AI.US', event, now[0].isoformat()))
        held, release = threading.Event(), threading.Event()
        def holder():
            with commit_fence():
                held.set()
                assert release.wait(4)
        thread = threading.Thread(target=holder, name='TEST_ONLY-CAS-fence-owner')
        thread.start()
        try:
            assert held.wait(4)
            for _ in range(2):
                worker._drain_events()
                assert worker.sink.qsize() == 1
                assert worker._pending_input_commit[0] is item
                assert worker.state['input_commit_state'] == 'WAIT_COMMIT'
            captured = worker._pending_input_commit[1]
            assert captured['received_at'] == item[3]
            assert worker.state['input_commit_busy_count'] == 2
            with sqlite3.connect(lane.minute_path) as db:
                assert db.execute('SELECT count(*) FROM one_minute_bars').fetchone()[0] == 5
        finally:
            release.set()
            thread.join(4)
        assert not thread.is_alive()
        now[0] += timedelta(seconds=1)
        worker._drain_events()
        assert worker._pending_input_commit is None and worker.sink.empty()
        with sqlite3.connect(lane.minute_path) as db:
            row = db.execute('SELECT payload_json FROM one_minute_bars WHERE evidence_id=?',
                             (common.digest(captured),)).fetchone()
        assert row and json.loads(row[0]) == captured


def test_existing_recovery_retains_completion_on_busy_without_provider_refetch(tmp_path):
    from kquant.options_one_minute_recovery import RecoveryLane
    with actual_lane(tmp_path) as (lane, _, now, _, job, bars, _):
        with sqlite3.connect(lane.minute_path) as db:
            db.execute('DELETE FROM one_minute_bars WHERE open_at=?', (bars[-1]['open_at'],))
        calls, delivered = [], []
        def captured(symbol, opened):
            calls.append((symbol, opened))
            return {'status': 'RECOVERED', 'bars': [bars[-1]]}
        recovery = RecoveryLane(lane.minute_path, captured, queue_path=lane.path, clock=lambda: now[0])
        recovery.restore_day = job[1].isoformat()
        policy = common.load_policy()
        recovery.observe(job[0], common.timestamp(bars[-1]['open_at']),
            {common.timestamp(b['open_at']): b for b in bars[:-1]}, policy, job[3])
        def tick():
            now[0] += timedelta(milliseconds=100)
            value = recovery.tick(job[1].isoformat(), policy, job[3])
            if value:
                delivered.append(value)
            return recovery.state.get('state') == 'JOURNAL_UNAVAILABLE'
        try:
            with commit_fence():
                until(tick)
                assert recovery.completion is not None and len(calls) == 1
                original_deadline = recovery.completion[0]['deadline_at']
                assert recovery.completion[1]['bars'] == [bars[-1]]
            until(lambda: (tick(), bool(delivered))[1])
            assert len(calls) == 1
            assert delivered[0]['job']['deadline_at'] == original_deadline
            assert delivered[0]['bars'] == [bars[-1]]
        finally:
            recovery.close()
            recovery.io.shutdown(wait=True, cancel_futures=True)
            recovery.provider.shutdown(wait=True, cancel_futures=True)


def test_action_busy_leaves_original_claim_until_existing_expiry(tmp_path):
    with actual_lane(tmp_path) as (lane, _, now, _, job, bars, _):
        write = writer('action', lane, job, bars, now[0], tmp_path)
        index = tmp_path/'TEST_ONLY-action-index.json'
        before = index.read_bytes()
        errors = []
        def attempt():
            try:
                write()
            except TimeoutError as exc:
                errors.append(exc)
        with commit_fence():
            thread = threading.Thread(target=attempt)
            thread.start()
            thread.join(1)
            assert not thread.is_alive() and len(errors) == 1
        assert index.read_bytes() == before
        scope = [{'symbol': job[0]}]
        assert actions.claim_action(index, scope, job[1], 'TEST_ONLY', now[0]) is None
        claimed = actions.claim_action(index, scope, job[1], 'TEST_ONLY', now[0]+timedelta(seconds=91))
        assert claimed[1]['lease_id'] != 'TEST_ONLY'


def test_action_partial_batch_notifies_committed_symbols_on_later_busy(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from kquant import options_opening_trend_runtime as runtime
    with actual_lane(tmp_path) as (lane, _, now, _, job, _, _):
        held, release = threading.Event(), threading.Event()
        calls, notifications = [], []
        def holder():
            with commit_fence():
                held.set()
                assert release.wait(4)
        thread = threading.Thread(target=holder)
        class TestOnlyActions:
            def corporate_actions(self, symbol, *, start_date, end_date):
                calls.append(symbol)
                if len(calls) == 2:
                    thread.start()
                    assert held.wait(4)
                return {'items': []}
        transport = TestOnlyActions()
        runner = SimpleNamespace(store=tmp_path/'TEST_ONLY-actions', _context=lambda: transport)
        original = runtime.notify_price_sources
        def notified(symbols, session):
            notifications.extend(symbols)
            return original(symbols, session)
        monkeypatch.setattr(runtime, 'notify_price_sources', notified)
        try:
            result = actions.refresh(runner, now=now[0], clock=lambda: now[0], root=tmp_path,
                reviews={}, scope=[{'symbol': s, 'identity_status': 'verified'} for s in ['AI', 'B']], batch_size=2)
            assert notifications == ['AI']
            assert result['input_commit_deferred'] == ['B']
            assert len(calls) == 2
            index = json.loads((runner.store/'price-actions/index.json').read_text())
            assert index['records']['B']['status'] == 'LEASED'
            assert len(list((runner.store/'price-actions').glob('*.json'))) == 3
        finally:
            release.set()
            if thread.ident:
                thread.join(4)
        assert not thread.is_alive()
