import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

import prepare_local_epoch as helper


@pytest.fixture
def root(tmp_path):
    source = Path(__file__).parent
    for name in ('new_data_epoch.py', 'cloud_archive_inventory.py'):
        target = tmp_path / 'source/development/handoff/tools' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / 'development/handoff/tools' / name, target)
    schema = tmp_path / 'source/development/workspace/kquant/options_one_minute.py'
    schema.parent.mkdir(parents=True)
    schema.write_text("SCHEMA = 'CREATE TABLE observations(id INTEGER PRIMARY KEY);'", encoding='utf-8')
    return tmp_path


def decision(review):
    # Isolated fixture, never written as production OWNER evidence.
    d = review['declaration']
    return {**{k: d[k] for k in ('runtime_root', 'minute_path', 'epoch_id', 'session')},
            'gate': 'O-SETUP', 'status': 'APPROVED', 'approved_by': 'OWNER',
            'decision': 'NEW_MINUTE_EPOCH', 'declaration_sha256': review['declaration_sha256'],
            'old_position_continuity': 'UNKNOWN', 'accepted_at': '2026-10-08T10:00:00+08:00',
            'human_decision_evidence': 'ISOLATED_TEST_FIXTURE_NOT_A_REAL_APPROVAL'}


def test_missing_acceptance_has_no_writes(root):
    review = helper.proposal(root, '2026-10-08', 'isolated-epoch')
    result = helper.evaluate(root, review, None, create=True)
    assert result['errors'] == [{'code': 'EXACT_DATA_SCOPE_ACCEPTANCE_REQUIRED'}]
    assert not (root / 'runtime').exists()


def test_exact_positive_and_repeat_refused(root):
    review = helper.proposal(root, '2026-10-08', 'isolated-epoch')
    result = helper.evaluate(root, review, decision(review), create=True)
    assert result['database_created'] and not result['can_launch']
    with sqlite3.connect(review['declaration']['minute_path']) as db:
        metadata = json.loads(db.execute('SELECT payload_json FROM data_epoch_boundary').fetchone()[0])
    assert metadata['old_position_continuity'] == 'UNKNOWN'
    assert not helper.evaluate(root, review, decision(review), create=True)['ok']


def test_epoch_is_not_daily_expiring(root):
    review = helper.proposal(root, '2026-10-08', 'isolated-epoch')
    assert helper.evaluate(root, review, decision(review))['ok']
    assert review['declaration']['session_semantics'].startswith('EPOCH_START')


@pytest.mark.parametrize('change', ['root', 'source', 'declaration', 'acceptance'])
def test_wrong_bindings_refused(root, change):
    review = helper.proposal(root, '2026-10-08', 'isolated-epoch')
    accepted = decision(review)
    if change == 'root':
        review['root'] = str(root / 'different-machine')
    elif change == 'source':
        review['source_sha256'] = '0' * 64
    elif change == 'declaration':
        review['declaration']['session'] = '2026-10-09'
    else:
        accepted['epoch_id'] = 'another-epoch'
    if change == 'acceptance':
        assert not helper.evaluate(root, review, accepted, create=True)['ok']
    else:
        with pytest.raises(ValueError):
            helper.evaluate(root, review, accepted, create=True)
    assert not (root / 'runtime').exists()


def test_fault_drive_rejected_without_probe(root):
    with pytest.raises(ValueError, match='PATH_OUTSIDE_SAFE_ROOT'):
        helper.ordinary(Path('F:/unread'), root)
