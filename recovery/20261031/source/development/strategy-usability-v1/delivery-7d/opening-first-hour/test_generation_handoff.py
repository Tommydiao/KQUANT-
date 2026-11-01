"""Real worker/lane constructors, TEST_ONLY inputs and deterministic race barriers."""
from contextlib import contextmanager
from datetime import date, timedelta
from hashlib import sha256
import json
import queue
import sqlite3
import threading
import time

import pytest

import first_hour
import first_hour_journal as journal
from first_hour_runtime import TrendLane
from kquant import options_one_minute as common
from kquant.options_one_minute_runtime import OneMinuteResearchWorker
from method_snapshot import calculation_scope
from prepared_generation import GenerationChanged


class TestOnlyTransport:
    __test__ = False

    def event_queue(self, *args, **kwargs):
        return queue.Queue()


class TestOnlyHub:
    __test__ = False

    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


def until(predicate, seconds=6):
    end = time.monotonic()+seconds
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.01)
    assert predicate(), 'TEST_ONLY_BARRIER_NOT_REACHED'


@contextmanager
def actual_lane(tmp_path):
    minute, research = tmp_path/'minute'/'minute.sqlite3', tmp_path/'research'/'research.sqlite3'
    minute.parent.mkdir()
    research.parent.mkdir()
    common.initialize(minute)
    reviews = tmp_path/'reviews.json'
    reviews.write_text('{}', encoding='utf-8')
    day = date(2026, 10, 22)
    opening, _ = first_hour.session_bounds_utc(day)
    now = [opening]
    hub = TestOnlyHub()
    worker = OneMinuteResearchWorker(tmp_path/'unused-main.sqlite3', hub,
        path=minute, clock=lambda: now[0], runtime=TestOnlyTransport())
    lane = TrendLane(minute, hub, path=research, clock=lambda: now[0],
                     source_root=tmp_path, source_reviews_path=reviews)
    worker.trend_lane = lane
    worker.day = day
    worker.manifest = {'scope_hash': 'TEST_ONLY'}
    native = dict(symbol='AI', provider_symbol='AI.US', currency='USD',
        source='LONGBRIDGE_SECURITY_STATIC_INFO', received_at=opening.isoformat())
    native['source_hash'] = common.digest(native)
    reference = {'raw_quote': {'symbol': 'AI', 'provider_status': 'available',
        'currency': 'USD', 'currency_evidence': native,
        'received_at': opening.isoformat(), 'requested_at': opening.isoformat(),
        'quote_time': opening.isoformat(), 'previous_close': 99}}
    worker.trend_references['AI'] = reference
    bars = [dict(symbol='AI', interval='1m', open_at=(opening+timedelta(minutes=i)).isoformat(),
        available_at=(opening+timedelta(minutes=i+1)).isoformat(),
        received_at=(opening+timedelta(minutes=i+1)).isoformat(), closed=True,
        open=100+i, high=102+i, low=99+i, close=101+i, volume=1000, turnover=100000,
        sdk_evidence={'provider_symbol': 'AI.US', 'adjustment': 'NoAdjust',
                      'interface': 'QuoteContext.candlesticks'}) for i in range(5)]
    for bar in bars:
        worker._record(bar)  # Real persistence and owner -> lane notification.
    lane.history.request('AI', day)
    until(lambda: lane.history.completed == 1)
    now[0] = opening+timedelta(minutes=5, seconds=1)
    lane.history.request('AI', day)
    until(lambda: lane.history.completed == 2 and lane.input_epochs.get(('AI', day), 0) == 2)
    job = ('AI', day, bars, 'TEST_ONLY', reference)
    key = ('opening_momentum', day.isoformat(), 'AI', 1)
    with lane.lock:
        lane.latest_inputs[job[:2]] = job
    try:
        yield lane, worker, now, key, job, bars, reviews
    finally:
        lane.close()
        worker.provider_jobs.shutdown(wait=True, cancel_futures=True)
        worker.risk_jobs.shutdown(wait=True, cancel_futures=True)
        assert not lane.writer.is_alive() and not lane.thread.is_alive()


def prepare(lane, key, job):
    with lane._input_batch(entries=[(key, job)]):
        return lane._prepare_generation(key, job, lane.input_epochs.get(job[:2], 0),
                                        lane._source_reviews(), first_hour.policies())


def validate(lane, value):
    return lane._validate_generation(value, reviews=lane._source_reviews(), policy_pair=first_hour.policies())


def results(path):
    with sqlite3.connect(path) as db:
        return [json.loads(row[0]) for row in db.execute('SELECT payload_json FROM evaluations')]


def dispatch(lane, key, job):
    with lane.lock:
        lane.checkpoints[key] = job
        lane.incoming[key] = job
        lane.lock.notify_all()


def test_actual_worker_lane_prepare_once_handoff_and_independent_s1(tmp_path, monkeypatch):
    with actual_lane(tmp_path) as (lane, worker, now, key, job, bars, reviews):
        calls = []
        aggregations = []
        original_aggregate = first_hour.s0.price_aggregate
        def aggregate(rows):
            aggregations.append(len(rows))
            return original_aggregate(rows)
        monkeypatch.setattr(first_hour.s0, 'price_aggregate', aggregate)
        original = lane._checkpoint_inputs
        def measured(*args, **kwargs):
            calls.append(threading.current_thread().name)
            return original(*args, **kwargs)
        monkeypatch.setattr(lane, '_checkpoint_inputs', measured)
        dispatch(lane, key, job)
        until(lambda: len(results(lane.path)) == 4)
        assert calls == ['opening-checkpoint-journal']
        assert lane.state['generation_preparations'] == 1
        assert lane.state['generation_handoffs'] == 1
        assert aggregations == [5]  # Shared across S0/S1 and Call/Put, not four aggregations.
        rows = results(lane.path)
        assert all(row['state'] == 'INCOMPLETE' for row in rows if row['policy_hash'] == first_hour.policies()['S0']['policy_hash'])
        assert all(row['state'] in {'NO_TRIGGER', 'NUMERIC_PASS'} for row in rows
                   if row['policy_hash'] == first_hour.policies()['S1']['policy_hash'])
        assert len({row['runtime_inputs']['input_generation'] for row in rows}) == 1


def test_prepared_content_is_deeply_immutable(tmp_path):
    with actual_lane(tmp_path) as (lane, _, _, key, job, _, _):
        generation = prepare(lane, key, job)
        with pytest.raises(TypeError):
            generation.job[2][0]['close'] = 0
        with pytest.raises(TypeError):
            generation.minute_inputs[0].append({})
        with pytest.raises(TypeError):
            generation.minute_inputs[2]['missing_slots'].clear()
        validate(lane, generation)


def test_timing_preserves_end_to_end_and_separates_actual_commit(tmp_path):
    with actual_lane(tmp_path) as (lane, _, _, key, job, _, _):
        lane.timings[key] = {'enqueue_monotonic': time.monotonic()}
        dispatch(lane, key, job)
        until(lambda: any('runtime_timing' in event for event in lane.hub.events))
        timing = next(event['runtime_timing'] for event in lane.hub.events if 'runtime_timing' in event)
        for field in ('admission_queue_seconds','compute_queue_seconds',
                      'generation_preparation_cpu_seconds','generation_validation_cpu_seconds',
                      'commit_fence_wait_seconds','commit_validation_seconds','commit_journal_seconds',
                      'commit_batch_cpu_seconds','enqueue_to_durable_commit_seconds'):
            assert timing[field] >= 0
        assert timing['enqueue_to_durable_commit_seconds'] <= timing['enqueue_to_commit_seconds']
        assert abs(timing['commit_batch_seconds']-sum(timing[field] for field in
            ('commit_fence_wait_seconds','commit_validation_seconds','commit_journal_seconds'))) < 1e-6


def test_missing_enqueue_time_is_not_a_zero_latency_sample(tmp_path):
    with actual_lane(tmp_path) as (lane, _, _, key, job, _, _):
        dispatch(lane, key, job)
        until(lambda: any('runtime_timing' in event for event in lane.hub.events))
        timing = next(event['runtime_timing'] for event in lane.hub.events if 'runtime_timing' in event)
        assert timing['enqueue_to_durable_commit_seconds'] is None
        assert timing['enqueue_to_commit_seconds'] is None
        assert timing['admission_queue_seconds'] is None


def test_real_enqueue_adds_timestamp_to_existing_diagnostic_entry(tmp_path):
    with actual_lane(tmp_path) as (lane, _, _, key, job, bars, _):
        lane.timings[key] = {'input_batch_read_seconds': 0.1}
        lane.enqueue(job[0], job[1], bars, job[3], job[4])
        original = lane.timings[key]['enqueue_monotonic']
        lane.enqueue(job[0], job[1], bars, job[3], job[4])
        assert lane.timings[key]['enqueue_monotonic'] == original


def test_actual_lane_binds_fact_root_once_but_rejects_environment_change(tmp_path, monkeypatch):
    from kquant import options_price_action_source as actions
    calls = []
    original = actions.fact_data_root
    def observed(root):
        calls.append(root)
        return original(root)
    monkeypatch.setattr(actions, 'fact_data_root', observed)
    with actual_lane(tmp_path) as (lane, _, _, key, job, _, _):
        generation = prepare(lane, key, job)
        prepare(lane, key, job)
        validate(lane, generation)
        assert calls == [tmp_path]
        monkeypatch.setenv('KQUANT_RUNTIME_DATA_ROOT', str(tmp_path/'other'))
        with pytest.raises(GenerationChanged, match='RUNTIME_PATH_BINDING_ENVIRONMENT_CHANGED'):
            validate(lane, generation)


def test_bound_path_receipt_same_size_change_fails_before_compute(tmp_path, monkeypatch):
    # The real constructor/path validator is covered by assembly; isolate this
    # post-construction byte guard without mutating a production role map.
    with actual_lane(tmp_path) as (lane, _, _, key, job, _, _):
        receipt = tmp_path/'TEST_ONLY-bound-map.json'
        receipt.write_bytes(b'AAAA')
        expected = sha256(b'AAAA').hexdigest()
        monkeypatch.setenv('KQUANT_RUNTIME_PATH_BINDING', str(receipt))
        monkeypatch.setenv('KQUANT_RUNTIME_PATH_BINDING_SHA256', expected)
        lane.bound_path_environment = lane._path_environment()
        generation = prepare(lane, key, job)
        receipt.write_bytes(b'BBBB')
        with pytest.raises(GenerationChanged, match='RUNTIME_PATH_BINDING_BYTES_CHANGED'):
            validate(lane, generation)


def test_minute_only_owner_update_preserves_same_scope_native_reference(tmp_path):
    with actual_lane(tmp_path) as (lane, worker, now, key, job, bars, _):
        original_reference = json.loads(json.dumps(job[4]))
        worker.trend_references.pop('AI')
        worker._record(bars[-1])
        with lane.lock:
            assert lane.latest_inputs[job[:2]][4] == original_reference
        until(lambda: len(results(lane.path)) >= 4)
        s1 = [r for r in results(lane.path)
              if r['policy_hash'] == first_hour.policies()['S1']['policy_hash']]
        assert s1 and all(r['state'] in {'NO_TRIGGER', 'NUMERIC_PASS'} for r in s1)


def test_missing_reference_never_crosses_scope_or_overrides_explicit_failure(tmp_path):
    with actual_lane(tmp_path) as (lane, _, _, _, job, bars, _):
        lane.enqueue('AI', job[1], bars, job[3], {})
        with lane.lock:
            assert lane.latest_inputs[job[:2]][4] == {}
        lane.reference_ready('AI', job[1], job[4])
        lane.enqueue('AI', job[1], bars, 'TEST_ONLY_DIFFERENT_SCOPE', None)
        with lane.lock:
            assert lane.latest_inputs[job[:2]][4] == {}


def test_source_paths_deduplicate_before_os_resolution_without_caching_bytes(tmp_path, monkeypatch):
    from pathlib import Path
    from prepared_generation import source_files
    proof = tmp_path/'TEST_ONLY-proof.json'
    proof.write_bytes(b'AAAA')
    original = Path.resolve
    calls = []
    def observed(path, *args, **kwargs):
        calls.append(str(path))
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'resolve', observed)
    values = [{'source_path': proof.name, 'acceptance_path': proof.name} for _ in range(55)]
    first = source_files(tmp_path, values, extra=(proof, proof))
    assert len(calls) == 2  # root and named file; explicit bound path stays logical.
    assert first == ((original(proof), sha256(b'AAAA').hexdigest()),)
    proof.write_bytes(b'BBBB')
    assert source_files(tmp_path, values)[0][1] == sha256(b'BBBB').hexdigest()
    assert source_files(tmp_path, {'source_path': '../outside-proof'}) == ()


def test_scoped_file_tokens_recheck_bytes_before_return(tmp_path, monkeypatch):
    import prepared_generation as module
    from method_snapshot import SourceSnapshotChanged
    proof = tmp_path/'TEST_ONLY-scope-proof'
    proof.write_bytes(b'AAAA')
    calls = []
    original = module.file_token
    def observed(path):
        calls.append(path)
        return original(path)
    monkeypatch.setattr(module, 'file_token', observed)
    with calculation_scope():
        for _ in range(8):
            assert module.scoped_file_token(proof) == sha256(b'AAAA').hexdigest()
    assert len(calls) == 2  # One preparation and one original-byte exit check.
    with pytest.raises(SourceSnapshotChanged, match='METHOD_CHANGED'):
        with calculation_scope():
            module.scoped_file_token(proof)
            proof.write_bytes(b'BBBB')
            module.scoped_file_token(proof)
    assert module.scoped_file_token(proof) == sha256(b'BBBB').hexdigest()


@pytest.mark.parametrize('phase', ['admission', 'precommit'])
def test_scope_byte_change_cannot_escape_to_durable_completion(tmp_path, monkeypatch, phase):
    with actual_lane(tmp_path) as (lane, _, _, key, job, _, _):
        source = tmp_path/'TEST_ONLY-changing-source'
        source.write_bytes(b'AAAA')
        job[4]['source_path'] = source.name
        calls = []
        target = '_prepare_generation' if phase == 'admission' else '_validate_generation'
        original = getattr(lane, target)
        def changed(*args, **kwargs):
            value = original(*args, **kwargs)
            calls.append(True)
            if len(calls) == (1 if phase == 'admission' else 2):
                source.write_bytes(b'BBBB')
            return value
        monkeypatch.setattr(lane, target, changed)
        dispatch(lane, key, job)
        until(lambda: len(results(lane.path)) == 4)
        if phase == 'precommit':
            assert all(row['runtime_inputs']['input_generation'] >= 2 for row in results(lane.path))
        assert source.read_bytes() == b'BBBB'
        assert len(calls) >= (2 if phase == 'admission' else 4)


def test_phase_database_identity_check_precedes_journal_commit(tmp_path, monkeypatch):
    import generation_reads
    with actual_lane(tmp_path) as (lane, _, _, key, job, _, _):
        calls, calculations, finish_counts = [], [], []
        fail_next = [False]
        original_identity = generation_reads.identity
        original_validate, original_calculate = lane._validate_generation, lane._calculate
        original_finish = journal.finish_many
        def validate_once(*args, **kwargs):
            value = original_validate(*args, **kwargs)
            calls.append(True)
            if len(calls) == 2:
                fail_next[0] = True
            return value
        def identity_once(path):
            if fail_next[0]:
                fail_next[0] = False
                return ('TEST_ONLY', 'changed')
            return original_identity(path)
        def calculate(*args, **kwargs):
            calculations.append(True)
            return original_calculate(*args, **kwargs)
        def finish(*args, **kwargs):
            finish_counts.append(len(calculations))
            return original_finish(*args, **kwargs)
        monkeypatch.setattr(lane, '_validate_generation', validate_once)
        monkeypatch.setattr(lane, '_calculate', calculate)
        monkeypatch.setattr(generation_reads, 'identity', identity_once)
        monkeypatch.setattr(journal, 'finish_many', finish)
        dispatch(lane, key, job)
        until(lambda: lane.state.get('error') == 'ValueError')
        assert results(lane.path) == [] and finish_counts == []
        # Identity failures do not automatically adopt another database. A new
        # explicit source notification re-arms the unchanged TEST_ONLY store.
        assert lane.source_facts_ready('AI', job[1])
        until(lambda: len(results(lane.path)) == 4)
        assert finish_counts and min(finish_counts) >= 2


def test_legacy_lane_without_generation_commits_both_directions(tmp_path, monkeypatch):
    from kquant import options_opening_trend as legacy
    # Missing historical policy remains unavailable in production. This local
    # fixture covers only the existing WAIT_TREND route through actual CAS.
    fixture = tmp_path/'TEST_ONLY-legacy-wait-policy.json'
    fixture.write_text(json.dumps(dict(policy_id=legacy.POLICY_ID, test_only=True,
        qualified_publication_enabled=False, paper_enabled=False,
        automatic_paper_enabled=False, real_orders_enabled=False, llm_required=False,
        bedtime_timezone='Asia/Shanghai', bedtime_exit='01:30', bedtime_reminder='01:15',
        planned_exit_minutes_before_close=30, entry_window_minutes=30)), encoding='utf-8')
    monkeypatch.setattr(legacy, 'CONFIG', fixture)
    with actual_lane(tmp_path) as (lane, _, _, key, job, _, _):
        legacy_key = ('opening_trend', *key[1:])
        with lane.lock:
            lane.checkpoints[legacy_key] = job
            lane.pending[legacy_key] = job
            lane.lock.notify_all()
        until(lambda: len(results(lane.path)) == 2 or lane.state.get('error'))
        assert len(results(lane.path)) == 2, lane.state
        rows = results(lane.path)
        assert {row['right'] for row in rows} == {'CALL', 'PUT'}
        assert all(row['state'] == 'WAIT_TREND' for row in rows)
        assert all(row['runtime_inputs']['input_generation'] is None for row in rows)
        assert not lane.state.get('generation_invalidations')
        assert not lane.state.get('generation_invalidation_reason')


@pytest.mark.parametrize('mutation', ['same_size_minute', 'minute_revision', 'source_file', 'clock_epoch'])
def test_generation_rejects_durable_and_clock_changes(tmp_path, monkeypatch, mutation):
    with actual_lane(tmp_path) as (lane, worker, now, key, job, bars, reviews):
        source = tmp_path/'proof.txt'
        source.write_bytes(b'AAAA')
        job[4]['source_path'] = 'proof.txt'
        generation = prepare(lane, key, job)
        if mutation == 'same_size_minute':
            with sqlite3.connect(lane.minute_path) as db:
                row = db.execute('SELECT evidence_id,payload_json FROM one_minute_bars LIMIT 1').fetchone()
                original = row[1]
                changed = original.replace('"close":101', '"close":102')
                assert changed != original and len(changed) == len(original)
                db.execute('UPDATE one_minute_bars SET payload_json=? WHERE evidence_id=?', (changed, row[0]))
        elif mutation == 'minute_revision':
            common.save_bar({**bars[-1], 'close': 103, 'received_at': now[0].isoformat()}, job[1].isoformat(), lane.minute_path)
        elif mutation == 'source_file':
            source.write_bytes(b'BBBB')
        else:
            from kquant import options_clock_measurement as measurement
            monkeypatch.setattr(measurement, '_attachment', dict(measurement._attachment))
            monkeypatch.setattr(measurement, '_published_time', measurement._published_time)
            measurement.publish({'state': 'CLOCK_DISCONTINUITY', 'precision_verified': False,
                                 'source_hash': 'TEST_ONLY_NEW_CLOCK_EPOCH'})
        with pytest.raises(GenerationChanged):
            validate(lane, generation)


def test_method_expiry_while_queued_revalidates_real_receipt(tmp_path):
    from first_hour_minute_decisions import LOCAL_METHOD
    with actual_lane(tmp_path) as (lane, _, now, key, job, _, reviews):
        receipt = {'approved_by': 'OWNER', 'status': 'APPROVED', 'test_only': True,
            'method_hash': common.digest(LOCAL_METHOD), 'approved_at': now[0].isoformat(),
            'valid_until': (now[0]+timedelta(seconds=1)).isoformat()}
        raw = json.dumps(receipt).encode()
        (tmp_path/'TEST_ONLY-receipt.json').write_bytes(raw)
        proof = {'semantics': 'CLOSED_SNAPSHOT_ADOPTION', 'status': 'ACCEPTED',
            'method': LOCAL_METHOD, 'acceptance_path': 'TEST_ONLY-receipt.json',
            'acceptance_sha256': sha256(raw).hexdigest()}
        reviews.write_text(json.dumps({'canonical_resolution_method': proof}))
        generation = prepare(lane, key, job)
        validate(lane, generation)
        now[0] += timedelta(seconds=1)
        with pytest.raises(GenerationChanged, match='TIME_BOUNDARY'):
            validate(lane, generation)


def test_time_admission_change_advances_fingerprint_without_fabricated_input(tmp_path):
    with actual_lane(tmp_path) as (lane, _, now, key, job, bars, _):
        with sqlite3.connect(lane.minute_path) as db:
            db.execute('DELETE FROM one_minute_bars WHERE open_at=?', (bars[-1]['open_at'],))
        future = {**bars[-1], 'received_at': (now[0]+timedelta(seconds=1)).isoformat()}
        common.save_bar(future, job[1].isoformat(), lane.minute_path)
        earlier = prepare(lane, key, job)
        assert earlier.minute_inputs[1]
        now[0] += timedelta(seconds=1)
        with pytest.raises(GenerationChanged, match='TIME_BOUNDARY'):
            validate(lane, earlier)
        later = prepare(lane, key, job)
        assert not later.minute_inputs[1]
        assert later.minute_token == earlier.minute_token
        assert later.fingerprint != earlier.fingerprint


def test_source_update_during_compute_old_completion_cannot_commit(tmp_path, monkeypatch):
    with actual_lane(tmp_path) as (lane, _, _, key, job, _, reviews):
        entered, release = threading.Event(), threading.Event()
        original = lane._calculate
        old_generations = []
        def blocked(*args, **kwargs):
            value = original(*args, **kwargs)
            if not entered.is_set():
                old_generations.append(args[4].generation)
                entered.set()
                assert release.wait(4)
            return value
        monkeypatch.setattr(lane, '_calculate', blocked)
        dispatch(lane, key, job)
        try:
            assert entered.wait(4), lane.state
            reviews.write_text('{"test_only_revision":2}')
            assert lane.source_facts_ready('AI', job[1])
            until(lambda: lane.state.get('generation_preparations', 0) >= 2)
        finally:
            release.set()
        until(lambda: len(results(lane.path)) == 4)
        assert all(row['runtime_inputs']['input_generation'] > old_generations[0] for row in results(lane.path))
        assert lane.state['generation_invalidations'] >= 1


def test_equivalent_update_during_compute_rearms_same_generation(tmp_path, monkeypatch):
    with actual_lane(tmp_path) as (lane, _, _, key, job, _, _):
        entered, release = threading.Event(), threading.Event()
        original = lane._calculate
        def blocked(*args, **kwargs):
            value = original(*args, **kwargs)
            if not entered.is_set():
                entered.set()
                assert release.wait(4)
            return value
        monkeypatch.setattr(lane, '_calculate', blocked)
        dispatch(lane, key, job)
        try:
            assert entered.wait(4), lane.state
            lane.source_facts_ready('AI', job[1])  # Exact same facts, newer notification epoch.
            until(lambda: lane.state.get('generation_preparations', 0) >= 2)
        finally:
            release.set()
        until(lambda: len(results(lane.path)) == 4)
        assert all(row['runtime_inputs']['input_generation'] == 1 for row in results(lane.path))
        assert lane.state['generation_invalidations'] >= 1


def test_update_after_admission_before_handoff_is_not_lost(tmp_path, monkeypatch):
    with actual_lane(tmp_path) as (lane, _, _, key, job, _, reviews):
        entered, release = threading.Event(), threading.Event()
        original = journal.ready_many
        def admitted(*args, **kwargs):
            value = original(*args, **kwargs)
            if not entered.is_set():
                entered.set()
                assert release.wait(4)
            return value
        monkeypatch.setattr(journal, 'ready_many', admitted)
        dispatch(lane, key, job)
        try:
            assert entered.wait(4)
            reviews.write_text('{"test_only_revision":3}')
            assert lane.source_facts_ready('AI', job[1])
        finally:
            release.set()
        until(lambda: len(results(lane.path)) == 4)
        assert all(row['runtime_inputs']['input_generation'] == 2 for row in results(lane.path))


def test_wait_input_registration_race_is_not_lost(tmp_path, monkeypatch):
    with actual_lane(tmp_path) as (lane, worker, now, key, job, bars, _):
        with sqlite3.connect(lane.minute_path) as db:
            db.execute('DELETE FROM one_minute_bars WHERE open_at=?', (bars[-1]['open_at'],))
        original = journal.finish_many
        delivered = []
        def finish_and_deliver(*args, **kwargs):
            outcome = original(*args, **kwargs)
            if not delivered and any(outcome):
                delivered.append(True)
                worker._record(bars[-1])
            return outcome
        monkeypatch.setattr(journal, 'finish_many', finish_and_deliver)
        dispatch(lane, key, job)
        until(lambda: any(row['state'] in {'NO_TRIGGER', 'NUMERIC_PASS'}
                          for row in results(lane.path)))
        assert delivered
        with sqlite3.connect(lane.path) as db:
            payload = json.loads(db.execute('SELECT payload_json FROM two_hour_jobs WHERE job_id=?',
                (journal.identity(key, job[3]),)).fetchone()[0])
        assert payload['input_generation'] >= 2
        assert payload['completed_generation'] == payload['input_generation']


def test_deadline_cas_rejects_late_result(tmp_path):
    with actual_lane(tmp_path) as (lane, _, now, key, job, _, _):
        generation = prepare(lane, key, job)
        entries = [(key, generation.job, now[0], generation.fingerprint)]
        admitted = journal.ready_many(lane.path, entries, return_leases=True)[0]
        generation = generation.admitted(admitted)
        lease = journal.begin_many(lane.path, entries)[0]
        now[0] = generation.deadline
        assert not journal.finish(lane.path, lease, waiting=True, now=now[0])
        assert results(lane.path) == []


@pytest.mark.parametrize('change', ['expiry', 'clock'])
def test_cas_rechecks_boundary_after_precommit_validation(tmp_path, change):
    with actual_lane(tmp_path) as (lane, _, now, key, job, _, _):
        generation = prepare(lane, key, job)
        entries = [(key, generation.job, now[0], generation.fingerprint)]
        journal.ready_many(lane.path, entries)
        lease = journal.begin_many(lane.path, entries)[0]
        validate(lane, generation)
        lease.valid_before = now[0]+timedelta(seconds=1)
        lease.boundary_guard = lambda: change != 'clock'
        if change == 'expiry':
            now[0] += timedelta(seconds=1)
        assert not journal.finish(lane.path, lease, waiting=True, now=now[0])
        with sqlite3.connect(lane.path) as db:
            state, reason = db.execute('SELECT state,reason FROM two_hour_jobs WHERE job_id=?', (str(lease),)).fetchone()
        assert (state, reason) == ('READY', 'PREPARED_BOUNDARY_CHANGED')
        assert results(lane.path) == []


def test_restart_rebuilds_handoff_from_existing_lease(tmp_path):
    with actual_lane(tmp_path) as (lane, _, now, key, job, _, reviews):
        generation = prepare(lane, key, job)
        entries = [(key, generation.job, now[0], generation.fingerprint)]
        journal.ready_many(lane.path, entries)
        lease = journal.begin_many(lane.path, entries)[0]
        lane.close()
        restarted = TrendLane(lane.minute_path, TestOnlyHub(), path=lane.path,
            clock=lambda: now[0], source_root=tmp_path, source_reviews_path=reviews)
        try:
            until(lambda: len(results(restarted.path)) >= 4)
            assert restarted.state['restored_checkpoints'] == 1
            assert restarted.state['generation_preparations'] >= 1
            assert restarted.state['generation_handoffs'] >= 1
            assert journal.finish(restarted.path, lease, now=now[0]) is False
            with sqlite3.connect(lane.path) as db:
                deadline = db.execute('SELECT deadline_at FROM two_hour_jobs WHERE job_id=?', (str(lease),)).fetchone()[0]
            assert deadline == generation.deadline.isoformat()
        finally:
            restarted.close()
