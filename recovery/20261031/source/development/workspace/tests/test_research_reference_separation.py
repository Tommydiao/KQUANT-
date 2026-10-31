"""TEST_ONLY: missing contract facts do not erase independent price research."""
from copy import deepcopy

import pytest

from kquant import options_opening_momentum as model
from kquant.options_opening_trend_contracts import compare, reference_from_inspections
from kquant.options_opening_trend_pipeline import contract_record
from test_options_opening_momentum import inputs


def case(tmp_path):
    args = inputs()
    original = model.evaluate(**args)
    snapshot = dict(contract_symbol='TEST261005C105000.US', underlying_symbol='TEST',
                    direction='CALL', expiry_date='2026-10-05', strike_price=105,
                    currency='USD', delta=.525, contract_multiplier=100,
                    bid=1, ask=1.05, bid_size=3, ask_size=4,
                    bbo_received_at=args['now'].isoformat(),
                    calc_received_at=args['now'].isoformat())
    row = contract_record(snapshot, evidence={}, now=args['now'], root=tmp_path)
    return args, original, row


def test_missing_facts_retains_specific_reference_not_qualified(tmp_path):
    args, original, row = case(tmp_path)
    before = deepcopy(original)
    policy = model.load_policy()
    result = compare(original, [row], now=args['now'], policy=policy)
    reference = reference_from_inspections(original, [row], policy=policy)
    assert original == before and original['state'] == 'NUMERIC_PASS'
    assert not result['qualified_signal']
    assert result['groups']['extended']['selected'] is None
    assert reference['contract_id'] == 'TEST261005C105000.US'
    assert reference['expiry_date'] == '2026-10-05'
    assert reference['strike'] == 105 and reference['dte'] == 3
    assert reference['bid'] == 1 and reference['ask'] == 1.05
    assert reference['reference_only'] is True
    assert reference['multiplier'] is None
    assert reference['bid_size'] is None and reference['raw_bid_size'] == 3
    assert reference['deliverable'] == 'UNKNOWN'


@pytest.mark.parametrize('changes', [
    {'underlying': 'OTHER'}, {'right': 'PUT'}, {'expiry_date': '2026-10-04'},
    {'strike': 0}, {'contract_id': None}, {'expiry_date': 'invalid'},
])
def test_reference_does_not_guess_identity_or_extend_dte(tmp_path, changes):
    _, original, row = case(tmp_path)
    row.update(changes)
    assert reference_from_inspections(original, [row], policy=model.load_policy()) is None


def test_persistent_job_keeps_reference_without_approval_and_expires(tmp_path):
    from datetime import datetime, timedelta
    from types import SimpleNamespace
    from kquant import options_opening_trend_jobs as jobs
    from kquant import options_opening_trend_store as store
    from kquant.options_opening_trend_pipeline import step

    args, original, row = case(tmp_path)
    now = args['now']
    policy = model.load_policy()
    path = tmp_path / 'TEST_ONLY-research.sqlite3'
    store.initialize(path)
    store.persist([original], path)
    calls = []

    def record(name, value):
        calls.append(name)
        return value

    services = SimpleNamespace(
        event=lambda *_: record('event', {'trade_eligible': False, 'sources': {},
            'event_decision': {'decision': 'WARN', 'warnings': ['TEST_ONLY_MISSING_SOURCE'],
                'checked_at': now.isoformat(), 'valid_until': (now + timedelta(seconds=60)).isoformat()}}),
        expiries=lambda *_: record('expiries', {'expiries': [row['expiry_date']]}),
        chain=lambda *_: record('chain', {'contracts': [
            {'call_symbol': row['contract_id'], 'strike_price': row['strike']}]}),
        greeks=lambda *_: record('greeks', {'items': [
            {'contract_symbol': row['contract_id'], 'delta': .525}]}),
        contract=lambda *_: record('contract', deepcopy(row)),
        spot=lambda *_: {'symbol': original['symbol'], 'last': original['entry_range'][0],
                        'received_at': now.isoformat()},
        current_trend=lambda *_: {**{k: original[k] for k in ('symbol', 'session', 'policy_hash', 'scope_hash')},
            'state': 'VALID', 'bar_end': now.replace(second=0, microsecond=0).isoformat(),
            'checked_at': now.isoformat(), 'valid_until': (now + timedelta(seconds=3)).isoformat(),
            'factors': {'day_open': 100, 'previous_close': 99}},
        scope_hash=lambda: original['scope_hash'],
        approval=lambda *_: {'qualified_signal_pipeline_enabled': False, 'selected_expiry_group': None},
    )
    for _ in range(6):
        job = jobs.claim(path, now=now)
        assert job is not None
        progress, finished, revision = step(job, services, clock=lambda: now, policy=policy)
        assert jobs.settle(path, job, now=now, progress=progress, finished=finished, revision=revision)
    assert calls == ['event', 'expiries', 'chain', 'greeks', 'contract']
    saved = store.detail(original['evaluation_id'], path)
    assert saved['state'] == 'NUMERIC_PASS'
    assert saved['deadline_at'] == original['deadline_at']
    current = saved['current_eligibility']
    assert current['state'] == 'PENDING'
    assert current['reference_contract']['contract_id'] == row['contract_id']
    assert current['reference_contract_status'] == 'UNVERIFIED_REFERENCE'
    assert 'CONTRACT_NOT_QUALIFIED' in current['reasons']
    assert 'EXACT_POLICY_NOT_APPROVED' in current['reasons']
    assert 'EVENT_COVERAGE_NOT_ELIGIBLE' not in current['reasons']
    assert 'published_candidate' not in saved
    deadline = datetime.fromisoformat(original['deadline_at'])
    assert jobs.claim(path, now=deadline) is None
    expired = store.detail(original['evaluation_id'], path)
    assert expired['current_eligibility']['state'] == 'EXPIRED'
    assert expired['state'] == 'NUMERIC_PASS'
    assert expired['deadline_at'] == original['deadline_at']
