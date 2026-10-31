from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json

from kquant.options_price_action_source import claim_action, commit_action


def test_parallel_claims_and_expired_owner_cannot_commit(tmp_path):
    path = tmp_path / 'index.json'
    now = datetime(2026, 10, 12, tzinfo=UTC)
    scope = [{'symbol': 'AAPL', 'identity_status': 'verified'}]
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: claim_action(path, scope, now.date(), 'v1', now), range(2)))
    assert sum(row is not None for row in claims) == 1
    old = next(row for row in claims if row is not None)[1]
    new = claim_action(path, scope, now.date(), 'v1', now + timedelta(seconds=61))[1]
    assert new['lease_id'] != old['lease_id']
    assert not commit_action(path, 'AAPL', old, {}, tmp_path / 'raw.json', tmp_path,
                             now.date(), 1, now + timedelta(seconds=62))
    assert json.loads(path.read_text())['records']['AAPL']['lease_id'] == new['lease_id']


def test_first_and_renewal_lanes_alternate_across_reload(tmp_path):
    path = tmp_path / 'index.json'
    now = datetime(2026, 10, 12, tzinfo=UTC)
    records = {symbol: {'target_session': now.date().isoformat(), 'attempts': 1,
                        'status': 'READY', 'valid_until': now.isoformat(), 'method_hash': 'v1'}
               for symbol in ['AAPL', 'MSFT']}
    path.write_text(json.dumps({'records': records}))
    scope = [{'symbol': symbol, 'identity_status': 'verified'} for symbol in ['AAPL', 'MSFT', 'NVDA']]
    assert claim_action(path, scope, now.date(), 'v1', now)[0]['symbol'] == 'AAPL'
    assert claim_action(path, scope, now.date(), 'v1', now)[0]['symbol'] == 'NVDA'
    assert claim_action(path, scope, now.date(), 'v1', now)[0]['symbol'] == 'MSFT'
