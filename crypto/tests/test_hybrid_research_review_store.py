import sqlite3

import pytest

from kquant_crypto.hybrid_multifactor_sidecar import review_plan_evidence
from kquant_crypto.hybrid_research_review_store import ResearchReviewStore


def review(signal):
    return review_plan_evidence({'scope': 'DEV_ONLY', 'runtime_enabled': False,
        'version': 'multifactor_entry_student_t_dev_v1'},
        {'signal_time': signal, 'entry': 100, 'stop': 90, 'target': 120},
        purpose='DEV_ONLY', model_available_at=None, training_label_cutoff=None)


def test_reopen_reorder_idempotency_and_no_overwrite(tmp_path):
    path = tmp_path / 'independent.sqlite3'
    rows = [review(100), review(200)]
    with sqlite3.connect(path) as conn:
        store = ResearchReviewStore(conn)
        assert store.ingest('r', {'scope': 'DEV_ONLY'}, rows, recorded_at='now')['inserted'] == 2
    with sqlite3.connect(path) as conn:
        store = ResearchReviewStore(conn)
        assert store.ingest('r', {'scope': 'DEV_ONLY'}, list(reversed(rows)), recorded_at='later')['idempotent'] == 2
        changed = dict(rows[0], reasons=['changed'])
        with pytest.raises(ValueError):
            store.ingest('r', {'scope': 'DEV_ONLY'}, [changed], recorded_at='later')
        assert conn.execute('SELECT COUNT(*) FROM research_reviews').fetchone()[0] == 2


def test_database_failure_rolls_back_whole_batch():
    conn = sqlite3.connect(':memory:')
    store = ResearchReviewStore(conn)
    conn.execute('''CREATE TRIGGER fail_second BEFORE INSERT ON research_reviews
        WHEN (SELECT COUNT(*) FROM research_reviews)>0 BEGIN SELECT RAISE(ABORT,'injected'); END''')
    with pytest.raises(sqlite3.IntegrityError):
        store.ingest('r', {'scope': 'DEV_ONLY'}, [review(100), review(200)], recorded_at='now')
    assert conn.execute('SELECT COUNT(*) FROM research_reviews').fetchone()[0] == 0
    assert conn.execute('SELECT COUNT(*) FROM research_review_runs').fetchone()[0] == 0


def test_formal_database_and_permissions_rejected():
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE actual_orders (id TEXT)')
    with pytest.raises(ValueError):
        ResearchReviewStore(conn)
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='research_reviews'").fetchone()[0] == 0
    store = ResearchReviewStore(sqlite3.connect(':memory:'))
    with pytest.raises(ValueError):
        store.ingest('r', {'scope': 'DEV_ONLY'}, [dict(review(100), allowed_paper=True)], recorded_at='now')
