import sqlite3
from types import SimpleNamespace

import pytest

from kquant_crypto.hybrid_factor_journal import FactorJournal
from kquant_crypto.hybrid_multifactor_dev import CORE_SYMBOLS


def open_journal(path):
    return FactorJournal(path, first_close=3600, receipt_basis='REPLAY_CLOCK_FIXTURE', source='test')


def seed(j):
    for i, symbol in enumerate(CORE_SYMBOLS):
        j.ingest(str(i), symbol, SimpleNamespace(start=0, open=100, high=102,
                 low=99, close=101, volume=1000), received_at=3601, closed=True)


def test_restart_and_duplicate_frozen_result(tmp_path):
    path = tmp_path / 'research.db'
    j = open_journal(path)
    seed(j)
    expected = j.advance('freeze', 3601)
    assert len(expected) == 3
    j.close()
    j = open_journal(path)
    assert j.advance('freeze', 3601) == expected
    assert j.advance('next', 3602) == []
    assert j.db.execute('SELECT COUNT(*) FROM factor_events').fetchone()[0] == 5
    j.close()


def test_database_failure_does_not_consume_inputs(tmp_path):
    j = open_journal(tmp_path / 'research.db')
    seed(j)
    j.db.execute("CREATE TRIGGER reject_freeze BEFORE INSERT ON factor_events WHEN NEW.event_id='freeze' BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError, match='injected'):
        j.advance('freeze', 3601)
    assert j.db.execute('SELECT COUNT(*) FROM factor_events').fetchone()[0] == 3
    j.db.execute('DROP TRIGGER reject_freeze')
    assert len(j.advance('freeze', 3601)) == 3
    j.close()


def test_changed_event_or_stored_snapshot_rejected(tmp_path):
    j = open_journal(tmp_path / 'research.db')
    seed(j)
    j.advance('freeze', 3601)
    with pytest.raises(ValueError, match='correction'):
        j.advance('freeze', 3602)
    j.db.execute("UPDATE factor_events SET result='[]' WHERE event_id='freeze'")
    j.db.commit()
    with pytest.raises(ValueError, match='integrity'):
        j.advance('next', 3603)
    j.close()


def test_foreign_database_untouched(tmp_path):
    path = tmp_path / 'foreign.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE original_evidence(id INTEGER)')
    with pytest.raises(ValueError, match='independent'):
        open_journal(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [('original_evidence',)]


def test_contract_change_rejected(tmp_path):
    path = tmp_path / 'research.db'
    open_journal(path).close()
    with pytest.raises(ValueError, match='contract'):
        FactorJournal(path, first_close=3600, receipt_basis='OBSERVED_RECEIPT', source='test')


def test_other_connection_commit_invalidates_cache(tmp_path):
    path = tmp_path / 'research.db'
    a, b = open_journal(path), open_journal(path)
    seed(a)
    assert len(a.advance('freeze', 3601)) == 3
    assert b.advance('later', 3700) == []
    with pytest.raises(ValueError, match='monotone'):
        a.advance('stale_clock', 3602)
    a.close()
    b.close()


def test_external_corruption_not_hidden_by_cache(tmp_path):
    path = tmp_path / 'research.db'
    j = open_journal(path)
    seed(j)
    j.advance('freeze', 3601)
    with sqlite3.connect(path) as other:
        other.execute("UPDATE factor_events SET result='[]' WHERE event_id='freeze'")
    with pytest.raises(ValueError, match='integrity'):
        j.advance('later', 3700)
    j.close()
