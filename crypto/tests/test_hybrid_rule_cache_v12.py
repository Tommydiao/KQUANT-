from dataclasses import replace
import pytest
from kquant_crypto.hybrid_mock_broker import SymbolRules, BrokerRejected
from kquant_crypto.hybrid_rule_cache_v12 import RuleCache, RuleSnapshot


def rule():
    return SymbolRules('BTCUSDT','BTC','USDT','.01','.001','.001','100','5','100000','1','100000',100)


def test_rule_availability_expiry_and_expected_version():
    cache = RuleCache()
    r = rule()
    cache.put(RuleSnapshot(r,10,'mock','SYNTHETIC_RULE_FIXTURE'))
    assert cache.get('BTCUSDT', now=20, expected_hash=r.rule_hash) == r
    for now in (9,101):
        with pytest.raises(BrokerRejected):
            cache.get('BTCUSDT', now=now, expected_hash=r.rule_hash)
    with pytest.raises(BrokerRejected):
        cache.get('BTCUSDT', now=20, expected_hash='old')


def test_refresh_retains_old_version_and_invalidates_plan():
    cache = RuleCache()
    r = rule()
    first = RuleSnapshot(r,10,'mock','SYNTHETIC_RULE_FIXTURE')
    cache.put(first)
    newer = RuleSnapshot(replace(r,min_notional='10',valid_until=150),20,'mock','SYNTHETIC_RULE_FIXTURE')
    cache.put(newer)
    assert len(cache.versions) == 2
    with pytest.raises(ValueError):
        cache.put(first)
    with pytest.raises(BrokerRejected):
        cache.get('BTCUSDT', now=30, expected_hash=r.rule_hash)


def test_actual_rules_not_misrepresented_by_fixture():
    with pytest.raises(ValueError):
        RuleSnapshot(rule(),10,'testnet','exchangeInfo')
