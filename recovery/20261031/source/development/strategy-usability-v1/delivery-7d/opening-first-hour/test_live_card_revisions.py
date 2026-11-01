from contextlib import closing
from copy import deepcopy
from datetime import timedelta
import sqlite3

import first_hour
from short_probe import inputs
from kquant import options_opening_trend_store as store


def fixture(path, count):
    args = inputs()
    template = first_hour.evaluate_comparison_pair(**args)[0]
    store.initialize(path)
    rows = []
    for i in range(count):
        row = deepcopy(template)
        row.update(evaluation_id=f'TEST_ONLY_{i}', state='NUMERIC_PASS',
                   evaluated_at=(args['now']+timedelta(milliseconds=i)).isoformat(),
                   deadline_at=(args['now']+timedelta(seconds=299)).isoformat())
        row.pop('strategy_comparison', None)
        row.pop('timeliness_policy', None)
        rows.append(row)
    # Direct historical revisions are a TEST_ONLY storage fixture, not live inputs.
    prepared = store.prepare_evaluations(rows)
    with closing(sqlite3.connect(path)) as db, db:
        db.executemany('INSERT INTO evaluations VALUES (?,?,?,?,?,?,?,?)', prepared.values)
    return args, rows


def query(path, args):
    return store.current_cards(path=path, session=args['opening'].date().isoformat(),
        scope_hash=args['scope_hash'], now=args['now']+timedelta(seconds=1),
        policy=first_hour.load_policy())


def test_many_live_revisions_are_one_current_position(tmp_path):
    path = tmp_path/'TEST_ONLY.sqlite3'
    args, rows = fixture(path, 250)
    result = query(path, args)
    assert result['evaluations_total'] == 1
    assert result['evaluations'][0]['evaluation_id'] == rows[-1]['evaluation_id']
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT count(*) FROM evaluations').fetchone()[0] == 250


def test_latest_incomplete_does_not_resurrect_older_trigger(tmp_path):
    path = tmp_path/'TEST_ONLY.sqlite3'
    args, rows = fixture(path, 3)
    row = deepcopy(rows[-1])
    row.update(evaluation_id='TEST_ONLY_incomplete', state='INCOMPLETE')
    prepared = store.prepare_evaluations([row])
    with closing(sqlite3.connect(path)) as db, db:
        db.executemany('INSERT INTO evaluations VALUES (?,?,?,?,?,?,?,?)', prepared.values)
    result = query(path, args)
    assert result['evaluations_total'] == 0
    assert result['evaluations'] == []


def test_other_scope_cannot_hide_current_position(tmp_path):
    path = tmp_path/'TEST_ONLY.sqlite3'
    args, rows = fixture(path, 3)
    row = deepcopy(rows[-1])
    row.update(evaluation_id='TEST_ONLY_other_scope', scope_hash='OTHER', state='INCOMPLETE')
    prepared = store.prepare_evaluations([row])
    with closing(sqlite3.connect(path)) as db, db:
        db.executemany('INSERT INTO evaluations VALUES (?,?,?,?,?,?,?,?)', prepared.values)
    result = query(path, args)
    assert result['evaluations_total'] == 1
    assert result['evaluations'][0]['evaluation_id'] == rows[-1]['evaluation_id']
