from contextlib import closing
from datetime import date, timedelta
import json
import sqlite3

import first_hour
import first_hour_journal as journal
from short_probe import inputs
from kquant import options_opening_trend_store as store
from kquant import options_research_availability as availability


def test_original_admission_survives_revision_and_recovery(tmp_path):
    path = tmp_path / 'TEST_ONLY.sqlite3'
    journal.initialize(path)
    day = date(2026, 11, 2)
    opening, _ = first_hour.session_bounds_utc(day)
    scope = 'TEST_ONLY'
    journal.register_clock_positions(path, [{'symbol':'TEST','identity_status':'verified'}], day, scope, opening)
    key = ('opening_momentum', day.isoformat(), 'TEST', 11)
    job = ('TEST', day, [], scope, {})
    admitted = opening + timedelta(minutes=55, seconds=1)
    journal.ready(path, key, job, admitted, fingerprint='one')
    lease = journal.begin(path, key, job, admitted, fingerprint='one')
    assert lease.original_enqueued_at == admitted.isoformat()
    journal.restore(path, admitted + timedelta(seconds=2))
    journal.ready(path, key, job, admitted + timedelta(seconds=31), fingerprint='two')
    revised = journal.begin(path, key, job, admitted + timedelta(seconds=31), fingerprint='two')
    assert revised.original_enqueued_at == admitted.isoformat()
    row = {'original_enqueued_at':revised.original_enqueued_at}
    assert availability.timeliness(row, (admitted + timedelta(seconds=30)).isoformat())['state'] == 'TIMELY'
    assert availability.timeliness(row, (admitted + timedelta(seconds=30.001)).isoformat())['state'] == 'LATE'
    with closing(sqlite3.connect(path)) as db, db:
        raw = json.loads(db.execute('SELECT payload_json FROM two_hour_jobs WHERE job_id=?', (str(revised),)).fetchone()[0])
        raw.pop('original_enqueued_at')
        db.execute('UPDATE two_hour_jobs SET payload_json=? WHERE job_id=?', (json.dumps(raw), str(revised)))
    journal.ready(path, key, job, admitted + timedelta(seconds=32), fingerprint='three')
    legacy = journal.begin(path, key, job, admitted + timedelta(seconds=32), fingerprint='three')
    assert legacy.original_enqueued_at is None


def test_actual_math_commit_notifies_before_contract_and_late_result_is_history(tmp_path):
    path = tmp_path / 'TEST_ONLY.sqlite3'
    args = inputs()
    rows = first_hour.evaluate_comparison_pair(**args)
    assert rows[0]['strategy_comparison']['cohort']=='S1_INTRADAY_ONLY_DATA'
    origin = args['now'] - timedelta(seconds=31)
    for row in rows:
        for item in (row, row['strategy_comparison']['s1']):
            item.update(timeliness_policy=availability.TIMELINESS_POLICY, original_enqueued_at=origin.isoformat())
    store.initialize(path)
    journal.initialize(path)
    store.persist(rows, path)
    store.persist(rows, path)
    child = next(row['strategy_comparison']['s1'] for row in rows if row['right']=='CALL')
    with closing(sqlite3.connect(path)) as db:
        raw = db.execute('SELECT payload_json FROM revisions WHERE evaluation_id=?', (child['evaluation_id'],)).fetchall()
        assert len(raw)==1
        assert json.loads(raw[0][0])['stage']=='TECHNICAL_RESEARCH_READY'
        assert db.execute('SELECT count(*) FROM qualified_claims').fetchone()[0]==0
    before = store.detail(child['evaluation_id'], path)
    assert before['research_timeliness']['state']=='UNKNOWN'
    availability.record_many(path, rows, observed_at=args['now'])
    late = store.detail(child['evaluation_id'], path)
    assert late['research_timeliness']['state']=='LATE'
    assert not availability.current_allowed(late)
    current = store.current_cards(path=path, session=args['opening'].date().isoformat(),
        scope_hash=args['scope_hash'], now=args['now'] + timedelta(seconds=1),
        policy=first_hour.load_policy())
    assert current['evaluations'] == []
    assert current['candidates'] == []
    assert store.detail(child['evaluation_id'], path)['state'] == child['state']
    # A later observation cannot renew the immutable first availability.
    availability.record_many(path, rows, observed_at=args['now']+timedelta(seconds=5))
    assert store.detail(child['evaluation_id'], path)['research_timeliness']==late['research_timeliness']


def test_unknown_and_future_admission_never_become_current():
    assert availability.timeliness({}, '2026-11-02T14:35:05Z')['state']=='UNKNOWN'
    assert availability.timeliness({'original_enqueued_at':'2026-11-02T14:35:06Z'}, '2026-11-02T14:35:05Z')['state']=='UNKNOWN'
