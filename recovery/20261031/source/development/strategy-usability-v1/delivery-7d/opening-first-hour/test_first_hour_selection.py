from copy import deepcopy
from datetime import timedelta
import sqlite3
import pytest
from kquant import options_opening_trend_jobs as jobs
from kquant import options_opening_trend_store as store
from first_hour_policy import policy_for
from short_probe import prepare


def test_last_point_durable_selection_reference_and_expiry(tmp_path):
    path = tmp_path/'research.sqlite3'
    args, detail, events, transport = prepare(path)
    child = detail['strategy_comparison']['s1']
    assert child['state'] == 'NUMERIC_PASS'
    assert detail['state'] == 'INCOMPLETE'
    assert child['deadline_at'] == (args['opening']+timedelta(minutes=60)).isoformat()
    assert policy_for(child)['entry_window_minutes'] == 60
    assert set(transport.calls) == {'EVENT', 'EXPIRIES', 'CHAIN', 'GREEKS', 'CONTRACT'}
    assert jobs.claim(path, now=args['opening']+timedelta(minutes=60)) is None
    expired = store.detail(child['evaluation_id'], path)
    assert expired['current_eligibility']['state'] == 'EXPIRED'
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT count(*) FROM qualified_claims').fetchone()[0] == 0


def test_policy_hash_and_snapshot_cannot_be_forged(tmp_path):
    _, detail, _, _ = prepare(tmp_path/'research.sqlite3')
    child = detail['strategy_comparison']['s1']
    bad = deepcopy(child)
    bad['policy_hash'] = 'wrong'
    with pytest.raises(ValueError, match='POLICY_OR_SCOPE_CHANGED'):
        policy_for(bad, validate=False)
    bad = deepcopy(child)
    bad['policy_snapshot']['contracts']['quote_age_seconds'] = 999
    with pytest.raises(ValueError, match='POLICY_SNAPSHOT_MISMATCH'):
        policy_for(bad)
