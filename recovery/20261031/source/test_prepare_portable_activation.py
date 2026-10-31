from hashlib import sha256
import json
from pathlib import Path
import sqlite3

import pytest
from kquant import recovery_activation
from test_prepare_local_epoch import root, decision
import prepare_local_epoch as epoch
import prepare_portable_activation as helper


def fixture(root):
    review = epoch.proposal(root, '2026-10-08', 'TEST_ONLY-isolated-copy')
    accepted = decision(review)
    assert epoch.evaluate(root, review, accepted, create=True)['database_created']
    rp, ap = root / 'review.json', root / 'acceptance.json'
    helper.record(rp, review)
    helper.record(ap, accepted)
    preserved = root / 'preserved-stores'
    preserved.mkdir()
    stores = []
    for role in helper.ROLES:
        path = preserved / (role + '.sqlite3')
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE business(id INTEGER PRIMARY KEY, value TEXT)')
            db.execute("INSERT INTO business VALUES(1,'TEST_ONLY')")
        info = path.stat()
        stores.append({'role': role, 'file_identity': {'device': info.st_dev, 'inode': info.st_ino},
            'bytes': info.st_size, 'mtime_ns': info.st_mtime_ns,
            'sha256': sha256(path.read_bytes()).hexdigest(), 'integrity_check': ['ok'], 'bytes_unchanged': True,
            'selected_watermarks': [{'table': 'business', 'column': 'id'}]})
    helper.record(root / 'computer-handoff-restore-receipt.json', {
        'schema': 'KQUANT_PORTABLE_COMPUTER_HANDOFF_RESTORE_V1', 'inputs_verified': True,
        'restored': True, 'core_sha256': 'a'*64, 'preserved_snapshots': str(preserved),
        'core_restore': {'stores': stores}})
    return rp, ap


def test_real_copy_activation_and_idempotent_resume(root):
    rp, ap = fixture(root)
    result = helper.prepare(root, rp, ap, root / 'evidence', execute=True)
    assert result['ok'] and len(result['activation_receipts']) == 5
    assert not result['can_launch'] and result['old_position_continuity'] == 'UNKNOWN'
    paths = [root / 'runtime' / relative for relative in helper.ROLES.values()]
    ids = [p.stat().st_ino for p in paths]
    assert helper.prepare(root, rp, ap, root / 'evidence', execute=True)['ok']
    assert ids == [p.stat().st_ino for p in paths]
    results = sorted((root / 'evidence').glob('activation-result-*.json'))
    bound = helper.finalize_binding(root, root / 'evidence/activation-request.json', results[-1])
    assert not bound['can_launch'] and bound['old_position_continuity'] == 'UNKNOWN'
    from kquant.options_data_paths import resolve_stores
    from unittest.mock import patch
    with patch.dict('os.environ', {'KQUANT_RUNTIME_DATA_ROOT': str(root / 'runtime'),
            'KQUANT_RUNTIME_PATH_BINDING': bound['runtime_path_binding']['path'],
            'KQUANT_RUNTIME_PATH_BINDING_SHA256': bound['runtime_path_binding']['sha256']}):
        assert set(resolve_stores(root / 'source/development/workspace')) == {*helper.ROLES, 'minute'}


def test_changed_active_is_not_overwritten(root):
    rp, ap = fixture(root)
    assert helper.prepare(root, rp, ap, root / 'evidence', execute=True)['ok']
    active = root / 'runtime' / helper.ROLES['main']
    original = active.read_bytes()
    active.write_bytes(original.replace(b'TEST_ONLY', b'TEST_LOST'))
    with pytest.raises(ValueError, match='ACTIVE_CHANGED_NO_OVERWRITE'):
        helper.prepare(root, rp, ap, root / 'evidence', execute=True)
    assert b'TEST_LOST' in active.read_bytes()


def test_bad_scope_does_not_copy_preserved_database(root):
    rp, ap = fixture(root)
    accepted = json.loads(ap.read_text())
    accepted['epoch_id'] = 'wrong'
    ap.write_text(json.dumps(accepted))
    with pytest.raises(ValueError, match='EXACT_DATA_SCOPE_ACCEPTANCE_MISMATCH'):
        helper.prepare(root, rp, ap, root / 'evidence', execute=True)
    assert not (root / 'runtime' / helper.ROLES['main']).exists()
