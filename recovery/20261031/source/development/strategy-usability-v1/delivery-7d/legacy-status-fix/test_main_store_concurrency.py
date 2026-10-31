from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest
from overlay import install

install()
from kquant.main_store_runtime import prepare_read_concurrency


def fixture_store(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript('''CREATE TABLE stock_watchlist_groups(group_id TEXT, is_active INTEGER);
            CREATE TABLE stock_watchlist_members(normalized_symbol TEXT, provider_symbol TEXT,
                identity_status TEXT, group_id TEXT, status TEXT);
            CREATE TABLE writer_payload(id INTEGER PRIMARY KEY, payload TEXT);''')
        db.execute("INSERT INTO stock_watchlist_groups VALUES ('TEST_ONLY',1)")
        db.executemany('INSERT INTO stock_watchlist_members VALUES (?,?,?,?,?)',
            [(f'TEST{i}', f'TEST{i}.US', 'verified', 'TEST_ONLY', 'active') for i in range(111)])
        db.execute("INSERT INTO writer_payload VALUES (1,'original')")


def child_universe(path):
    program = '''import json,sqlite3,sys
from pathlib import Path
from kquant.options_two_hour_data import universe
try:
    rows = universe(Path(sys.argv[1]))
    print(json.dumps({'count':len(rows['items']), 'scope_hash':rows['scope_hash']}))
except sqlite3.Error as exc:
    print(json.dumps({'error':exc.sqlite_errorname}))
'''
    result = subprocess.run([sys.executable, '-c', program, str(path)],
        capture_output=True, text=True, timeout=3, check=True)
    return json.loads(result.stdout)


def test_cross_process_universe_reader_before_after_wal(tmp_path):
    path = tmp_path/'main.sqlite3'
    fixture_store(path)
    baseline = child_universe(path)
    assert baseline['count'] == 111
    with closing(sqlite3.connect(path)) as writer:
        writer.execute('BEGIN EXCLUSIVE')
        writer.execute("UPDATE writer_payload SET payload='pending'")
        assert child_universe(path) == {'error': 'SQLITE_BUSY'}
        writer.rollback()
    result = prepare_read_concurrency(path)
    assert result['previous_journal_mode'] == 'delete'
    assert result['journal_mode'] == 'wal' and result['changed']
    with closing(sqlite3.connect(path)) as writer:
        writer.execute('BEGIN EXCLUSIVE')
        writer.execute("UPDATE writer_payload SET payload='pending'")
        assert child_universe(path) == baseline
        writer.rollback()
        assert writer.execute('SELECT payload FROM writer_payload').fetchone()[0] == 'original'
    assert not prepare_read_concurrency(path)['changed']


def test_busy_startup_fails_closed_and_preserves_rows(tmp_path):
    path = tmp_path/'main.sqlite3'
    fixture_store(path)
    with closing(sqlite3.connect(path)) as writer:
        writer.execute('BEGIN EXCLUSIVE')
        with pytest.raises(sqlite3.OperationalError) as caught:
            prepare_read_concurrency(path)
        assert caught.value.sqlite_errorname == 'SQLITE_BUSY'
        writer.rollback()
        assert writer.execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
        assert writer.execute('SELECT COUNT(*) FROM stock_watchlist_members').fetchone()[0] == 111


def test_preparation_never_creates_missing_database(tmp_path):
    path = tmp_path/'missing.sqlite3'
    with pytest.raises(sqlite3.OperationalError):
        prepare_read_concurrency(path)
    assert not path.exists()
