from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from time import monotonic

import pytest
from overlay import install
install()
from kquant.recovery_preflight import evaluate, candidate_hash
from kquant.recovery_runtime_probe import observe_database, MINUTE_STATUS_SCHEMA
from test_new_epoch_runtime import epoch_candidate
from overlay import HERE
import kquant.recovery_preflight
assert Path(kquant.recovery_preflight.__file__).is_relative_to(HERE/'patches')


def rewrite(proof, value):
    assert value['test_only'] is True
    path = Path(proof['path'])
    path.write_text(json.dumps(value), encoding='ascii')
    proof['sha256'] = sha256(path.read_bytes()).hexdigest()


def resign(manifest):
    proof = manifest['acceptance_receipt']
    value = json.loads(Path(proof['path']).read_text())
    value.update(candidate_payload_sha256=candidate_hash(manifest),
                 continuity_receipt_sha256=manifest['continuity']['receipt']['sha256'])
    rewrite(proof, value)


def fixture(tmp_path):
    manifest = epoch_candidate(tmp_path)
    row = next(r for r in manifest['databases'] if r['role'] == 'minute')
    with closing(sqlite3.connect(row['path'])) as db:
        db.execute('CREATE TABLE one_minute_evaluations(session,symbol,right_name,created_at,bar_end,state,payload_json)')
    active = json.loads(Path(row['activation_receipt']['path']).read_text())
    observed = observe_database(dict(role='minute', path=row['path'], watermarks=active['watermarks'],
        epoch_boundary=active['epoch_boundary']), [str(tmp_path)], monotonic()+2)
    active['schema_sha256'] = observed['schema_sha256']
    rewrite(row['activation_receipt'], active)
    proof = manifest['continuity']['receipt']
    continuity = json.loads(Path(proof['path']).read_text())
    continuity['activation_receipts']['minute'] = row['activation_receipt']['sha256']
    rewrite(proof, continuity)
    row['schema_extension'] = 'MINUTE_STATUS_METADATA_INDEX_V1'
    resign(manifest)
    return manifest, row


def test_declared_minute_index_restart_preserves_five_roles_and_boundary(tmp_path):
    manifest, row = fixture(tmp_path)
    before = evaluate(manifest, roots=[tmp_path], allow_test_only=True)
    assert before['can_launch'], before['errors']
    with closing(sqlite3.connect(row['path'])) as db:
        old_boundary = db.execute('SELECT * FROM data_epoch_boundary').fetchall()
        db.execute(MINUTE_STATUS_SCHEMA[3])
        assert db.execute('SELECT * FROM data_epoch_boundary').fetchall() == old_boundary
    after = evaluate(manifest, roots=[tmp_path], allow_test_only=True)
    assert after['can_launch'], after['errors']
    assert after['database_opens'] == 5 and after['business_writes'] == 0
    found = next(r for r in after['schema_extension_observations'] if r['role'] == 'minute')
    assert found['compatible'] and found['observed']['present']
    assert after['old_position_continuity'] == 'UNKNOWN'


@pytest.mark.parametrize('change', ['columns', 'other_index', 'boundary', 'undeclared', 'wrong_role', 'unaccepted'])
def test_minute_extension_cannot_hide_other_changes(tmp_path, change):
    manifest, row = fixture(tmp_path)
    with closing(sqlite3.connect(row['path'])) as db, db:
        if change == 'columns':
            db.execute('CREATE INDEX one_minute_status_metadata ON one_minute_evaluations(symbol,session)')
        else:
            db.execute(MINUTE_STATUS_SCHEMA[3])
            if change == 'other_index':
                db.execute('CREATE INDEX unrelated ON one_minute_evaluations(state)')
            elif change == 'boundary':
                db.execute('DELETE FROM data_epoch_boundary')
    if change == 'undeclared':
        row.pop('schema_extension')
        resign(manifest)
    elif change == 'wrong_role':
        next(r for r in manifest['databases'] if r['role'] == 'main')['schema_extension'] = row.pop('schema_extension')
        resign(manifest)
    elif change == 'unaccepted':
        manifest['final_runtime_accepted'] = False
    result = evaluate(manifest, roots=[tmp_path], allow_test_only=True)
    assert not result['can_launch'], result
    expected = {'columns': 'DECLARED_INDEX_DEFINITION_CHANGED',
        'other_index': 'ACTIVE_DATABASE_SCHEMA_CHANGED', 'boundary': 'NEW_EPOCH_BOUNDARY_MISSING',
        'undeclared': 'ACTIVE_DATABASE_SCHEMA_CHANGED', 'wrong_role': 'UNSUPPORTED_SCHEMA_EXTENSION',
        'unaccepted': 'FINAL_RUNTIME_NOT_ACCEPTED'}[change]
    assert expected in {row['code'] for row in result['errors']}, result['errors']
    if change in {'wrong_role', 'unaccepted'}:
        assert result['database_opens'] == 0
