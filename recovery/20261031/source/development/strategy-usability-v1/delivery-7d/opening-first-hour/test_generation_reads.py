import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from generation_reads import read_scope, read_connection


def database(tmp_path, name='TEST_ONLY.sqlite3'):
    path = tmp_path/name
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE versions(value TEXT)')
        db.execute("INSERT INTO versions VALUES ('AAAA')")
    return path


def test_same_phase_reuses_handle_but_observes_committed_same_size_revision(tmp_path):
    path = database(tmp_path)
    with read_scope():
        with read_connection(path, seconds=.2) as first:
            assert first.execute('SELECT value FROM versions').fetchone()[0] == 'AAAA'
        with sqlite3.connect(path) as writer:
            writer.execute("UPDATE versions SET value='BBBB'")
        with read_connection(path, seconds=.2) as second:
            assert first is second
            assert second.execute('SELECT value FROM versions').fetchone()[0] == 'BBBB'
    with pytest.raises(sqlite3.ProgrammingError):
        first.execute('SELECT 1')
    with read_scope(), read_connection(path, seconds=.2) as third:
        assert third is not first


def test_missing_db_is_not_created(tmp_path):
    path = tmp_path/'absent.sqlite3'
    with pytest.raises((OSError, sqlite3.Error)), read_scope(), read_connection(path, seconds=.2):
        pass
    assert not path.exists()


def test_scope_closes_handles_on_error(tmp_path):
    path = database(tmp_path)
    with pytest.raises(RuntimeError), read_scope():
        with read_connection(path, seconds=.2) as db:
            raise RuntimeError('TEST_ONLY')
    with pytest.raises(sqlite3.ProgrammingError):
        db.execute('SELECT 1')


def test_query_only_and_nested_read_are_not_bypassed(tmp_path):
    path = database(tmp_path)
    with read_scope():
        with pytest.raises(sqlite3.OperationalError), read_connection(path, seconds=.2) as db:
            db.execute("UPDATE versions SET value='AAAA'")
        with read_connection(path, seconds=.2):
            with pytest.raises(ValueError, match='REENTRANCY'), read_connection(path, seconds=.2):
                pass


def test_budget_interrupt_does_not_poison_next_bounded_read(tmp_path):
    path = database(tmp_path)
    with read_scope():
        with pytest.raises(TimeoutError, match='STATUS_QUERY_BUDGET_EXCEEDED'):
            with read_connection(path, seconds=.001) as db:
                db.execute('WITH RECURSIVE seq(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM seq WHERE x<50000000) SELECT sum(x) FROM seq').fetchone()
        with read_connection(path, seconds=.2) as db:
            assert db.execute('SELECT value FROM versions').fetchone()[0] == 'AAAA'


def test_no_handle_sharing_between_threads(tmp_path):
    path = database(tmp_path)
    def read():
        with read_scope(), read_connection(path, seconds=.2) as other:
            return other, other.execute('SELECT count(*) FROM versions').fetchone()[0]
    with read_scope(), read_connection(path, seconds=.2) as current, ThreadPoolExecutor(max_workers=1) as pool:
        other, count = pool.submit(read).result(timeout=2)
        assert current is not other and count == 1


def test_handle_count_bound(tmp_path):
    paths = [database(tmp_path, f'TEST_ONLY-{i}.sqlite3') for i in range(3)]
    with read_scope():
        for path in paths[:2]:
            with read_connection(path, seconds=.2):
                pass
        with pytest.raises(ValueError, match='HANDLE_BOUND'), read_connection(paths[2], seconds=.2):
            pass


def test_file_identity_replacement_rejects_reuse(tmp_path, monkeypatch):
    import generation_reads
    path = database(tmp_path)
    with read_scope():
        with read_connection(path, seconds=.2):
            pass
        monkeypatch.setattr(generation_reads, 'identity', lambda _: ('TEST_ONLY', 'changed'))
        with pytest.raises(ValueError, match='FILE_IDENTITY_CHANGED'), read_connection(path, seconds=.2):
            pass


def test_phase_identity_is_rechecked_before_result_can_escape(tmp_path, monkeypatch):
    import generation_reads
    path = database(tmp_path)
    original, calls = generation_reads.identity, []
    def observed(p):
        calls.append(p)
        return original(p)
    monkeypatch.setattr(generation_reads, 'identity', observed)
    with read_scope(phase_checked=True):
        for _ in range(8):
            with read_connection(path, seconds=.2) as db:
                assert db.execute('SELECT value FROM versions').fetchone()[0] == 'AAAA'
    assert len(calls) == 3  # Before/open/phase-exit, not every SQL statement.
    with pytest.raises(ValueError, match='FILE_IDENTITY_CHANGED'):
        with read_scope(phase_checked=True):
            with read_connection(path, seconds=.2) as db:
                db.execute('SELECT 1').fetchone()
            monkeypatch.setattr(generation_reads, 'identity', lambda _: ('TEST_ONLY','changed'))
    with pytest.raises(sqlite3.ProgrammingError):
        db.execute('SELECT 1')


def test_phase_mode_still_sees_committed_content_updates(tmp_path):
    path = database(tmp_path)
    with read_scope(phase_checked=True):
        with read_connection(path, seconds=.2) as db:
            assert db.execute('SELECT value FROM versions').fetchone()[0] == 'AAAA'
        with sqlite3.connect(path) as writer:
            writer.execute("UPDATE versions SET value='BBBB'")
        with read_connection(path, seconds=.2) as db:
            assert db.execute('SELECT value FROM versions').fetchone()[0] == 'BBBB'
