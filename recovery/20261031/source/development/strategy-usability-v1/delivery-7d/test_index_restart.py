"""Real isolated launch-gate child checks; no production receipt is created."""
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from time import monotonic

import pytest

from kquant.recovery_preflight import evaluate, candidate_hash
from kquant.recovery_runtime_probe import observe_database, SOURCE_INDEX_SCHEMA
from test_new_epoch_runtime import epoch_candidate


def rewrite_test_receipt(proof, value):
    assert value['test_only'] is True
    path = Path(proof['path'])
    path.write_text(json.dumps(value), encoding='ascii')
    proof['sha256'] = sha256(path.read_bytes()).hexdigest()


def accepted_fixture(tmp_path):
    manifest = epoch_candidate(tmp_path)
    row = next(r for r in manifest['databases'] if r['role'] == 'opening_research')
    # Establish a TEST_ONLY baseline that already owns the continuation table.
    for field in ('path', 'recovery_path'):
        with closing(sqlite3.connect(row[field])) as db:
            db.execute('CREATE TABLE two_hour_jobs(session TEXT,symbol TEXT,queued_at TEXT)')
    original = Path(row['recovery_path'])
    receipt = json.loads(Path(row['receipt']['path']).read_text())
    receipt.update(bytes=original.stat().st_size, mtime_ns=original.stat().st_mtime_ns)
    rewrite_test_receipt(row['receipt'], receipt)
    active = json.loads(Path(row['activation_receipt']['path']).read_text())
    observation = observe_database(dict(role=row['role'], path=row['path'], watermarks=active['watermarks']),
        [str(tmp_path)], monotonic()+2)
    active.update(schema_sha256=observation['schema_sha256'], recovery_receipt_sha256=row['receipt']['sha256'])
    rewrite_test_receipt(row['activation_receipt'], active)
    continuity = json.loads(Path(manifest['continuity']['receipt']['path']).read_text())
    continuity['database_receipts'][row['role']] = row['receipt']['sha256']
    continuity['activation_receipts'][row['role']] = row['activation_receipt']['sha256']
    rewrite_test_receipt(manifest['continuity']['receipt'], continuity)
    row['schema_extension'] = 'OPENING_SOURCE_INDEX_V1'
    resign_fixture(manifest)
    return manifest, row


def resign_fixture(manifest):
    proof = manifest['acceptance_receipt']
    value = json.loads(Path(proof['path']).read_text())
    value.update(candidate_payload_sha256=candidate_hash(manifest),
        continuity_receipt_sha256=manifest['continuity']['receipt']['sha256'])
    rewrite_test_receipt(proof, value)


def test_exact_additive_index_allows_real_child_restart_without_business_change(tmp_path):
    manifest, row = accepted_fixture(tmp_path)
    before = evaluate(manifest, roots=[tmp_path], allow_test_only=True)
    assert before['can_launch'], before
    assert before['schema_extension_observations'][0]['observed']['present'] is False
    with closing(sqlite3.connect(row['path'])) as db:
        db.execute(SOURCE_INDEX_SCHEMA[3])
    after = evaluate(manifest, roots=[tmp_path], allow_test_only=True)
    assert after['can_launch'], after
    assert after['database_opens'] == 5 and after['business_writes'] == 0
    observed = after['schema_extension_observations'][0]
    assert observed['compatible'] and observed['observed']['present']
    assert observed['actual_schema_sha256'] != observed['baseline_schema_sha256']


@pytest.mark.parametrize('mutation', ['different_columns','unrelated_index','unrelated_table','rewrite_business'])
def test_extension_cannot_hide_any_other_change(tmp_path, mutation):
    manifest, row = accepted_fixture(tmp_path)
    with closing(sqlite3.connect(row['path'])) as db, db:
        if mutation == 'different_columns':
            db.execute('CREATE INDEX trend_input_source ON two_hour_jobs(symbol,session,queued_at)')
        else:
            db.execute(SOURCE_INDEX_SCHEMA[3])
            sql = {'unrelated_index': 'CREATE INDEX other_index ON two_hour_jobs(symbol)',
                'unrelated_table': 'CREATE TABLE other_data(id INTEGER)',
                'rewrite_business': "UPDATE business_events SET payload='changed' WHERE id=1"}[mutation]
            db.execute(sql)
    result = evaluate(manifest, roots=[tmp_path], allow_test_only=True)
    expected = ('DECLARED_INDEX_DEFINITION_CHANGED' if mutation == 'different_columns' else
        'ACTIVE_DATABASE_BUSINESS_BASELINE_CHANGED' if mutation == 'rewrite_business' else
        'ACTIVE_DATABASE_SCHEMA_CHANGED')
    assert expected in {r['code'] for r in result['errors']}, result
    assert not result['can_launch']


@pytest.mark.parametrize('mutation', ['missing','wrong_role','wrong_contract','unaccepted_change'])
def test_missing_or_unaccepted_extension_fails_closed(tmp_path, mutation):
    manifest, row = accepted_fixture(tmp_path)
    with closing(sqlite3.connect(row['path'])) as db:
        db.execute(SOURCE_INDEX_SCHEMA[3])
    if mutation == 'missing':
        row.pop('schema_extension')
        resign_fixture(manifest)
    elif mutation == 'wrong_role':
        other = next(r for r in manifest['databases'] if r['role'] == 'main')
        other['schema_extension'] = row.pop('schema_extension')
        resign_fixture(manifest)
    elif mutation == 'wrong_contract':
        row['schema_extension'] = 'ALLOW_ANY_SCHEMA'
        resign_fixture(manifest)
    else:
        row.pop('schema_extension')
    result = evaluate(manifest, roots=[tmp_path], allow_test_only=True)
    assert not result['can_launch']
    if mutation != 'missing':
        assert result['database_opens'] == 0


def test_method_acceptance_does_not_accept_schema_or_runtime(tmp_path):
    manifest, row = accepted_fixture(tmp_path)
    manifest['final_runtime_accepted'] = False
    result = evaluate(manifest, roots=[tmp_path], allow_test_only=True)
    assert not result['can_launch'] and result['database_opens'] == 0
