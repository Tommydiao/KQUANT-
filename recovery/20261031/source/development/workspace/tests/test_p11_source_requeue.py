from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

import pytest

from kquant.options_price_action_source import claim_action, requeue_after_condition_change


def setup(tmp_path):
    now = datetime(2026, 10, 12, 13, tzinfo=UTC)
    index = tmp_path / 'index.json'
    row = {'target_session': now.date().isoformat(), 'failures': 3, 'attempts': 3,
           'method_hash': 'method-v1', 'retry_after': (now + timedelta(hours=1)).isoformat(),
           'valid_until': now.isoformat()}
    index.write_text(json.dumps({'records': {'AAPL': row}}))
    evidence = tmp_path / 'TEST_ONLY-condition.json'
    evidence.write_text(json.dumps({'kind': 'SOURCE_CONDITION_CHANGE',
                                   'revision': 'TEST_ONLY-recovered-1', 'symbols': ['AAPL'],
                                   'target_session': now.date().isoformat()}))
    kwargs = dict(symbols=['AAPL'], target=now.date(), evidence_path=evidence,
                  evidence_sha256=sha256(evidence.read_bytes()).hexdigest(), now=now)
    return index, kwargs


def test_explicit_requeue_persists_without_refreshing_facts_or_reusing_revision(tmp_path):
    index, kwargs = setup(tmp_path)
    original = json.loads(index.read_text())['records']['AAPL']
    scope = [{'symbol': 'AAPL', 'identity_status': 'verified'}]
    assert claim_action(index, scope, kwargs['target'], 'method-v1', kwargs['now']) is None
    result = requeue_after_condition_change(index, **kwargs)
    assert result['released'] == ['AAPL']
    assert not result['source_fact_verified'] and not result['owner_approval']
    state = json.loads(index.read_text())
    assert state['records']['AAPL']['valid_until'] == original['valid_until']
    assert len(state['condition_requeue_history']) == 1
    assert claim_action(index, scope, kwargs['target'], 'method-v1', kwargs['now']) is not None
    assert requeue_after_condition_change(index, **kwargs)['unchanged'] == {
        'AAPL': 'CONDITION_REVISION_ALREADY_USED'}


@pytest.mark.parametrize('field,value,reason', [
    ('lease_until', '2026-10-12T13:00:30+00:00', 'LEASE_IN_FLIGHT'),
    ('coverage_method_blocked', True, 'SOURCE_METHOD_STILL_REQUIRED'),
    ('target_session', '2026-10-09', 'SESSION_OR_SYMBOL_NOT_FOUND'),
])
def test_requeue_cannot_bypass_inflight_method_or_session(tmp_path, field, value, reason):
    index, kwargs = setup(tmp_path)
    state = json.loads(index.read_text())
    state['records']['AAPL'][field] = value
    index.write_text(json.dumps(state))
    before = index.read_bytes()
    assert requeue_after_condition_change(index, **kwargs)['unchanged'] == {'AAPL': reason}
    assert index.read_bytes() == before


def test_requeue_rejects_tampered_or_out_of_scope_evidence(tmp_path):
    index, kwargs = setup(tmp_path)
    before = index.read_bytes()
    kwargs['evidence_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='HASH_MISMATCH'):
        requeue_after_condition_change(index, **kwargs)
    kwargs['evidence_sha256'] = sha256(kwargs['evidence_path'].read_bytes()).hexdigest()
    kwargs['symbols'] = ['MSFT']
    with pytest.raises(ValueError, match='SCOPE_MISMATCH'):
        requeue_after_condition_change(index, **kwargs)
    assert index.read_bytes() == before


def test_requeue_cannot_replay_an_older_condition_after_a_newer_one(tmp_path):
    index, kwargs = setup(tmp_path)
    requeue_after_condition_change(index, **kwargs)
    state = json.loads(index.read_text())
    state['records']['AAPL'].update(failures=3, last_condition_revision='TEST_ONLY-newer')
    index.write_text(json.dumps(state))
    assert requeue_after_condition_change(index, **kwargs)['unchanged'] == {
        'AAPL': 'CONDITION_REVISION_ALREADY_USED'}


def test_cli_operates_from_unrelated_working_directory(tmp_path):
    index, kwargs = setup(tmp_path)
    script = Path(__file__).absolute().parents[1] / 'scripts/requeue_price_action_source.py'
    result = subprocess.run([
        sys.executable, str(script), '--index', str(index), '--evidence', str(kwargs['evidence_path']),
        '--evidence-sha256', kwargs['evidence_sha256'], '--target-session',
        kwargs['target'].isoformat(), '--symbol', 'AAPL'], cwd=tmp_path,
        capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['released'] == ['AAPL']
