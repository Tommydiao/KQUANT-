from contextlib import closing
from pathlib import Path
import sqlite3
from time import monotonic

import pytest

from kquant.recovery_runtime_probe import observe_database, file_identity


def setup_pair(tmp_path):
    original, active = tmp_path / 'TEST_ONLY_original.sqlite3', tmp_path / 'TEST_ONLY_active.sqlite3'
    for path in (original, active):
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE copilot_meta(key TEXT PRIMARY KEY,value_json TEXT,updated_at TEXT)')
            db.execute('CREATE TABLE signals(id INTEGER PRIMARY KEY,payload TEXT)')
            db.executemany('INSERT INTO copilot_meta VALUES(?,?,?)',
                [('schema_version', '2', '2026-10-04T12:47:00Z'), ('engine_version', '"TEST_ONLY_v1"', '2026-10-04T12:47:00Z')])
            db.execute("INSERT INTO signals VALUES(1,'TEST_ONLY_KEEP')")
    request = {'role': 'signal_copilot', 'path': str(original), 'watermarks': [
        {'table': 'copilot_meta', 'column': 'rowid', 'minimum': 2},
        {'table': 'signals', 'column': 'id', 'minimum': 1}]}
    baseline = observe_database(request, [str(tmp_path)], monotonic()+2, capture_baseline=True)
    request.update(path=str(active), watermarks=baseline['watermarks'], metadata_baseline={
        'path': str(original), 'file_identity': file_identity(original)})
    with closing(sqlite3.connect(active)) as db, db:
        db.execute("INSERT OR REPLACE INTO copilot_meta VALUES('schema_version','2','2026-10-11T10:43:22Z')")
        db.execute("INSERT OR REPLACE INTO copilot_meta VALUES('engine_version','\"TEST_ONLY_v1\"','2026-10-11T10:43:22Z')")
    return request, baseline


def test_restart_metadata_retains_versions_without_faking_prefix(tmp_path):
    request, baseline = setup_pair(tmp_path)
    current = observe_database(request, [str(tmp_path)], monotonic()+2)
    mark = current['watermarks'][0]
    assert mark['initialization_metadata_compatible']
    assert mark['prefix_rows'] == 0
    assert mark['prefix_sha256'] != baseline['watermarks'][0]['prefix_sha256']
    assert current['watermarks'][1] == baseline['watermarks'][1]


@pytest.mark.parametrize('change', ['version', 'deleted', 'original_changed', 'identity'])
def test_metadata_exception_rejects_changed_values_and_untrusted_original(tmp_path, change):
    request, _ = setup_pair(tmp_path)
    path = Path(request['metadata_baseline']['path'] if change == 'original_changed' else request['path'])
    if change == 'identity':
        request['metadata_baseline']['file_identity'] = {'device': 0, 'inode': 0}
    else:
        with closing(sqlite3.connect(path)) as db, db:
            if change == 'deleted': db.execute("DELETE FROM copilot_meta WHERE key='engine_version'")
            else: db.execute("UPDATE copilot_meta SET value_json='\"TEST_ONLY_v2\"' WHERE key='engine_version'")
    current = observe_database(request, [str(tmp_path)], monotonic()+2)
    assert not current['watermarks'][0]['initialization_metadata_compatible']


def test_signal_tampering_stays_visible_when_metadata_is_compatible(tmp_path):
    request, baseline = setup_pair(tmp_path)
    with closing(sqlite3.connect(request['path'])) as db, db:
        db.execute("UPDATE signals SET payload='TEST_ONLY_TAMPER' WHERE id=1")
    current = observe_database(request, [str(tmp_path)], monotonic()+2)
    assert current['watermarks'][0]['initialization_metadata_compatible']
    assert current['watermarks'][1]['prefix_sha256'] != baseline['watermarks'][1]['prefix_sha256']
