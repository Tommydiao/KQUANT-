from contextlib import closing
import sqlite3

import pytest

from kquant import options_opening_momentum_journal as journal
from kquant import options_minute_decisions as decisions
from kquant import options_one_minute as common
from profile_decision_index import QUERY, ARGS


def test_source_index_is_additive_idempotent_and_used(tmp_path):
    path = tmp_path/'TEST_ONLY.sqlite3'
    journal.initialize(path)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('DROP INDEX trend_input_source')
        row = ('TEST_ONLY', ARGS[0], ARGS[1], '1', ARGS[2], ARGS[2],
               'WAIT_INPUT', None, None, 4, None, 'ORIGINAL', '{}')
        db.execute('INSERT INTO two_hour_jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', row)
    journal.initialize(path)
    journal.initialize(path)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT * FROM two_hour_jobs').fetchone() == row
        columns = [value[2] for value in db.execute('PRAGMA index_info(trend_input_source)')]
        assert columns == ['session', 'symbol', 'queued_at']
        plan = db.execute('EXPLAIN QUERY PLAN '+QUERY, ARGS).fetchall()
        assert any('USING INDEX trend_input_source' in value[-1] for value in plan)
        assert not any('TEMP B-TREE' in value[-1] for value in plan)


def test_reader_never_migrates_old_schema(tmp_path):
    path = tmp_path/'TEST_ONLY.sqlite3'
    journal.initialize(path)
    with closing(sqlite3.connect(path)) as db:
        db.execute('DROP INDEX trend_input_source')
    assert decisions.read(path, symbol=ARGS[1], session=ARGS[0], now=common.timestamp(ARGS[2])) == []
    with closing(sqlite3.connect(path)) as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='trend_input_source'").fetchone()


def test_index_initialization_respects_existing_lock_budget(tmp_path):
    path = tmp_path/'TEST_ONLY.sqlite3'
    journal.initialize(path)
    with closing(sqlite3.connect(path)) as db:
        db.execute('DROP INDEX trend_input_source')
        db.execute('BEGIN IMMEDIATE')
        with pytest.raises(sqlite3.OperationalError, match='locked'):
            journal.initialize(path)
        db.rollback()
    journal.initialize(path)
