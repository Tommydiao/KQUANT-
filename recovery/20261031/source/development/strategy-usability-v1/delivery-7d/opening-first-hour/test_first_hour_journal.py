from datetime import date, timedelta
import json
import sqlite3

import first_hour
import first_hour_journal as journal
from kquant import options_opening_momentum_journal as old


def test_fingerprint_reuses_existing_decision_digest(monkeypatch):
    day = date(2026, 10, 22)
    job = ('TEST', day, [], 'TEST_ONLY', {})
    decision = {'decision_hash': 'existing-hash', 'source_semantics': {'evidence': 'TEST_ONLY'}}
    original = journal.common.digest
    expected = journal.input_fingerprint(job, [decision])
    calls = []
    def measured(value):
        calls.append(value)
        return original(value)
    monkeypatch.setattr(journal.common, 'digest', measured)
    assert journal.input_fingerprint(job, [decision]) == expected
    assert not any(value is decision for value in calls)
    without_hash = {'source_semantics': {'evidence': 'TEST_ONLY'}}
    journal.input_fingerprint(job, [without_hash])
    assert any(value is without_hash for value in calls)


def test_full_registration_and_deadlines(tmp_path):
    path = tmp_path/'research.sqlite3'
    journal.initialize(path)
    day = date(2026, 10, 22)
    opening, _ = first_hour.session_bounds_utc(day)
    registered = [dict(symbol=f'TEST{i}', identity_status='verified') for i in range(100)]
    registered += [dict(symbol=f'UNKNOWN{i}', identity_status='unknown') for i in range(11)]
    result = journal.register_clock_positions(path, registered, day, 'TEST_ONLY', opening)
    assert result['inserted'] == 1100
    assert journal.register_clock_positions(path, registered, day, 'TEST_ONLY', opening)['inserted'] == 0
    with sqlite3.connect(path) as db:
        rows = db.execute('SELECT slot,deadline_at,payload_json FROM two_hour_jobs').fetchall()
    assert len(rows) == 1100
    assert {int(row[0]) for row in rows} == set(range(1, 12))
    for slot, deadline, raw in rows:
        expected = opening + timedelta(minutes=(int(slot)+1)*5)
        assert journal.common.timestamp(deadline) == expected
        assert json.loads(raw)['policy_hash'] == first_hour.policies()['S0']['policy_hash']
    result = journal.advance_clock_positions(path, registered, day, 'TEST_ONLY', opening+timedelta(minutes=60))
    assert result['expired_no_minute'] == 1100
    assert journal.restore(path, opening+timedelta(minutes=60)) == {}


def test_old_and_new_identity_and_restart(tmp_path):
    path = tmp_path/'research.sqlite3'
    journal.initialize(path)
    day = date(2026, 10, 22)
    opening, _ = first_hour.session_bounds_utc(day)
    key = ('opening_momentum', day.isoformat(), 'TEST', 5)
    job = ('TEST', day, [], 'TEST_ONLY', {})
    now = opening+timedelta(minutes=25, seconds=1)
    assert old.ready(path, key, job, now, fingerprint='old')
    assert journal.ready(path, key, job, now, fingerprint='new')
    assert old.identity(key, 'TEST_ONLY') != journal.identity(key, 'TEST_ONLY')
    assert len(journal.restore(path, now)) == 1
    key_last = (*key[:3], 11)
    last = opening+timedelta(minutes=55, seconds=1)
    assert journal.ready(path, key_last, job, last, fingerprint='generation-1')
    lease = journal.begin(path, key_last, job, last, fingerprint='generation-1')
    assert lease is not None
    assert key_last in journal.restore(path, last)
    assert journal.ready(path, key_last, job, last, fingerprint='generation-2')
    assert journal.finish(path, lease, waiting=True) is False
    new_lease = journal.begin(path, key_last, job, last, fingerprint='generation-2')
    assert journal.finish(path, new_lease, waiting=True)
    assert key_last in journal.restore(path, last)
    assert journal.begin(path, key_last, job, opening+timedelta(minutes=60), fingerprint='generation-2') is None


def test_late_start_never_backfills(tmp_path):
    path = tmp_path/'research.sqlite3'
    journal.initialize(path)
    day = date(2026, 10, 22)
    opening, _ = first_hour.session_bounds_utc(day)
    registered = [dict(symbol='GWH', identity_status='verified')]
    now = opening+timedelta(minutes=56)
    assert journal.register_clock_positions(path, registered, day, 'TEST_ONLY', now)['inserted'] == 1
    with sqlite3.connect(path) as db:
        state, slot = db.execute('SELECT state,slot FROM two_hour_jobs').fetchone()
    assert (state, slot) == ('WAIT_INPUT', '11')


def test_policy_read_once_per_operation_not_cached_between_calls(tmp_path, monkeypatch):
    path = tmp_path/'research.sqlite3'
    journal.initialize(path)
    day = date(2026, 10, 22)
    opening, _ = first_hour.session_bounds_utc(day)
    registered = [dict(symbol=f'TEST{i}', identity_status='verified') for i in range(100)]
    original = journal.load_policy
    calls = []
    def counted():
        calls.append(1)
        return original()
    monkeypatch.setattr(journal, 'load_policy', counted)
    assert journal.register_clock_positions(path, registered, day, 'TEST_ONLY', opening)['inserted'] == 1100
    assert len(calls) == 1
    journal.advance_clock_positions(path, registered, day, 'TEST_ONLY', opening+timedelta(minutes=5))
    assert len(calls) == 2
    entries = [(('opening_momentum', day.isoformat(), row['symbol'], 1),
                (row['symbol'], day, [], 'TEST_ONLY', {}),
                opening+timedelta(minutes=5, seconds=1), 'input') for row in registered[:64]]
    journal.ready_many(path, entries)
    assert len(calls) == 3
    journal.ready_many(path, entries)
    assert len(calls) == 4


def test_duplicate_ready_restores_volatile_wakeup_without_new_generation(tmp_path):
    path = tmp_path/'research.sqlite3'
    journal.initialize(path)
    day = date(2026, 10, 22)
    opening, _ = first_hour.session_bounds_utc(day)
    key = ('opening_momentum', day.isoformat(), 'AI', 2)
    job = ('AI', day, [], 'TEST_ONLY', {})
    now = opening+timedelta(minutes=10, seconds=1)
    entries = [(key, job, now, 'same-input')]
    assert journal.ready_many(path, entries) == [True]
    # The process-local pending notification can be lost after admission.
    assert journal.ready_many(path, entries) == [True]
    lease = journal.begin_many(path, entries)[0]
    assert lease is not None and lease.generation == 1
    assert journal.finish(path, lease, waiting=True)
    # Completed WAIT_INPUT must not spin on unchanged input.
    assert journal.ready_many(path, entries) == [False]
    assert journal.ready_many(path, [(key, job, now, 'revision')]) == [True]
    assert journal.ready_many(path, [(key, job, opening+timedelta(minutes=15), 'revision')]) == [False]
