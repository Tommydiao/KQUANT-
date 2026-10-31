"""TEST_ONLY real five-role probe process, including mutable watchlist time."""
from contextlib import closing
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
from time import monotonic

import pytest
from kquant.recovery_preflight import ROLES, evaluate
from kquant.recovery_runtime_probe import observe_database


def activated(tmp_path):
    root, original = tmp_path/'runtime', tmp_path/'original'
    root.mkdir()
    original.mkdir()
    def receipt(name, value):
        path = root/(name+'.json')
        path.write_text(json.dumps(dict(test_only=True, **value)), encoding='ascii')
        return dict(path=str(path), sha256=sha256(path.read_bytes()).hexdigest())
    source = receipt('source', dict(purpose='TEST_ONLY'))
    databases = []
    for role in sorted(ROLES):
        frozen, active = original/(role+'.sqlite3'), root/(role+'.sqlite3')
        marks = [dict(table='business_events', column='id', minimum=1)]
        with closing(sqlite3.connect(frozen)) as db:
            db.execute('CREATE TABLE business_events(id INTEGER PRIMARY KEY,payload TEXT)')
            db.execute("INSERT INTO business_events VALUES(1,'TEST_ONLY retained')")
            if role == 'main':
                db.execute('CREATE TABLE stock_watchlist_members(member_id INTEGER PRIMARY KEY,symbol TEXT,status TEXT,updated_at TEXT)')
                db.execute('INSERT INTO stock_watchlist_members VALUES(1,?,?,?)',
                    ('NVDA','active',(datetime.now(UTC)-timedelta(days=1)).isoformat()))
                marks.append(dict(table='stock_watchlist_members', column='rowid', minimum=1))
            db.commit()
        recovery = receipt(role+'-recovery', dict(role=role,database_path=str(frozen),
            bytes=frozen.stat().st_size,mtime_ns=frozen.stat().st_mtime_ns,
            integrity=['ok'],verified_at='TEST_ONLY',wal_shm=[]))
        shutil.copy2(frozen, active)
        observation = observe_database(dict(role=role,path=str(active),watermarks=marks),
            [str(tmp_path)],monotonic()+2,capture_baseline=True)
        activation = receipt(role+'-activation', dict(schema='KQUANT_DATABASE_ACTIVATION_V1',
            role=role,database_path=str(active),verified_at='TEST_ONLY',
            recovery_receipt_sha256=recovery['sha256'],file_identity=observation['file_identity'],
            schema_sha256=observation['schema_sha256'],watermarks=observation['watermarks'],
            baseline_file_identity=dict(device=frozen.stat().st_dev,inode=frozen.stat().st_ino)))
        databases.append(dict(role=role,path=str(active),recovery_path=str(frozen),
            recovery_state='COMPLETE_VERIFIED',receipt=recovery,activation_receipt=activation))
    continuity = receipt('continuity',dict(status='CONFIRMED',watermarks={r:1 for r in ROLES},
        unresolved_business_gaps=[],database_receipts={r['role']:r['receipt']['sha256'] for r in databases},
        activation_receipts={r['role']:r['activation_receipt']['sha256'] for r in databases}))
    deps = dict(verified_versions={'TEST_ONLY':'1'},active_paths=[str(root)])
    deps['receipt'] = receipt('deps',dict(status='VERIFIED',versions=deps['verified_versions'],active_paths=deps['active_paths']))
    acceptance = receipt('acceptance',dict(status='APPROVED',approved_by='OWNER',candidate_id='TEST_ONLY',
        runtime_root=str(root),continuity_receipt_sha256=continuity['sha256']))
    return dict(schema='KQUANT_SAFE_RECOVERY_V2',runtime_root=str(root),approved_runtime_root=str(root),
        candidate_id='TEST_ONLY',required_source=[source],frontend=[source],databases=databases,
        continuity=dict(status='CONFIRMED',reconciled_roles=sorted(ROLES),receipt=continuity),
        dependencies=deps,final_runtime_accepted=True,acceptance_receipt=acceptance)


def test_actual_probe_process_accepts_only_forward_metadata(tmp_path):
    manifest = activated(tmp_path)
    row = next(r for r in manifest['databases'] if r['role']=='main')
    with closing(sqlite3.connect(row['path'])) as db:
        db.execute('UPDATE stock_watchlist_members SET updated_at=?',(datetime.now(UTC).isoformat(),))
        db.execute("INSERT INTO business_events VALUES(2,'TEST_ONLY appended')")
        db.commit()
    result = evaluate(manifest,roots=[tmp_path],allow_test_only=True)
    assert result['can_launch'], result
    assert result['database_opens']==5 and result['business_writes']==0
    assert any(x['role']=='main' and x['compatible'] and x['only_mutable_field']=='updated_at'
        for x in result['initialization_metadata_observations'])


@pytest.mark.parametrize('sql',[
    "UPDATE stock_watchlist_members SET status='removed'",
    "UPDATE stock_watchlist_members SET symbol='OTHER'",
    'DELETE FROM stock_watchlist_members',
    "UPDATE stock_watchlist_members SET updated_at='invalid'",
    "UPDATE business_events SET payload='TEST_ONLY overwritten' WHERE id=1",
])
def test_actual_probe_process_rejects_business_change(tmp_path,sql):
    manifest=activated(tmp_path)
    row=next(r for r in manifest['databases'] if r['role']=='main')
    with closing(sqlite3.connect(row['path'])) as db:
        db.execute(sql)
        db.commit()
    result=evaluate(manifest,roots=[tmp_path],allow_test_only=True)
    assert not result['can_launch']
    assert any(x['code']=='ACTIVE_DATABASE_BUSINESS_BASELINE_CHANGED' for x in result['errors'])
