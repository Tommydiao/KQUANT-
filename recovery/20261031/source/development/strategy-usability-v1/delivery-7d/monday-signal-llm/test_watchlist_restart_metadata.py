from contextlib import closing
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sqlite3
from time import monotonic

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('watchlist_metadata_probe',
    HERE / 'metadata-followup/patches/kquant/recovery_runtime_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def fixture(tmp_path):
    old = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    rows = [(1, 'NVDA', 'active', old), (2, 'GWH', 'active', old)]
    paths = [tmp_path / 'baseline.sqlite3', tmp_path / 'active.sqlite3']
    for path in paths:
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE stock_watchlist_members(member_id INTEGER PRIMARY KEY, symbol TEXT, status TEXT, updated_at TEXT)')
            db.executemany('INSERT INTO stock_watchlist_members VALUES(?,?,?,?)', rows)
            db.commit()
    digest = sha256()
    for row in rows:
        digest.update(json.dumps(row, ensure_ascii=True, separators=(',', ':')).encode() + b'\n')
    mark = dict(table='stock_watchlist_members', column='rowid', minimum=2,
        prefix_rows=2, prefix_sha256=digest.hexdigest())
    request = dict(role='main', path=str(paths[1]), watermarks=[mark],
        metadata_baseline=dict(path=str(paths[0]), file_identity=probe.file_identity(paths[0])))
    return paths, mark, request


def compatible(paths, mark, request):
    with closing(sqlite3.connect(paths[1].as_uri() + '?mode=ro', uri=True)) as db:
        return probe.watchlist_timestamp_metadata_compatible(db, request, mark,
            [str(paths[0].parent)], monotonic() + 2)


def test_forward_timestamp_only_keeps_original_prefix(tmp_path):
    paths, mark, request = fixture(tmp_path)
    with closing(sqlite3.connect(paths[1])) as db:
        db.execute('UPDATE stock_watchlist_members SET updated_at=? WHERE member_id=1', (datetime.now(UTC).isoformat(),))
        db.commit()
    result = probe.observe_database(request, [str(tmp_path)], monotonic() + 2)
    assert result['watermarks'][0]['prefix_sha256'] != mark['prefix_sha256']
    assert result['watermarks'][0]['watchlist_timestamp_metadata_compatible'] is True


def test_same_values_are_compatible(tmp_path):
    paths, mark, request = fixture(tmp_path)
    assert compatible(paths, mark, request)


@pytest.mark.parametrize('sql,value', [
    ('UPDATE stock_watchlist_members SET status=? WHERE member_id=1', 'removed'),
    ('UPDATE stock_watchlist_members SET symbol=? WHERE member_id=1', 'DIFFERENT'),
    ('UPDATE stock_watchlist_members SET updated_at=? WHERE member_id=1', 'not-a-date'),
    ('UPDATE stock_watchlist_members SET updated_at=? WHERE member_id=1', None),
    ('UPDATE stock_watchlist_members SET updated_at=? WHERE member_id=1', '2000-01-01T00:00:00+00:00'),
    ('UPDATE stock_watchlist_members SET updated_at=? WHERE member_id=1', '2099-01-01T00:00:00+00:00'),
    ('UPDATE stock_watchlist_members SET updated_at=? WHERE member_id=1', '2026-10-18T00:00:00'),
])
def test_other_changes_still_reject(tmp_path, sql, value):
    paths, mark, request = fixture(tmp_path)
    with closing(sqlite3.connect(paths[1])) as db:
        db.execute(sql, (value,))
        db.commit()
    assert compatible(paths, mark, request) is False


def test_missing_prefix_row_rejects(tmp_path):
    paths, mark, request = fixture(tmp_path)
    with closing(sqlite3.connect(paths[1])) as db:
        db.execute('DELETE FROM stock_watchlist_members WHERE member_id=1')
        db.commit()
    assert compatible(paths, mark, request) is False


def test_changed_baseline_cannot_bless_active_data(tmp_path):
    paths, mark, request = fixture(tmp_path)
    with closing(sqlite3.connect(paths[0])) as db:
        db.execute("UPDATE stock_watchlist_members SET status='removed' WHERE member_id=1")
        db.commit()
    assert compatible(paths, mark, request) is False


def test_wrong_role_cannot_use_watchlist_exception(tmp_path):
    paths, mark, request = fixture(tmp_path)
    request['role'] = 'minute'
    assert compatible(paths, mark, request) is False
