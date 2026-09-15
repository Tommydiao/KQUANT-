from copy import deepcopy

import pytest

from test_candidate_portfolio import warm_states, warmed, trigger, bar, RULES, SYMBOLS
from kquant_crypto.hybrid_mc_portfolio_v12 import evaluate_path, ExistingExposurePortfolio
from kquant_crypto.candidate_policy import load_policy, digest
from kquant_crypto.candidate_simulation import CandidatePortfolio


def prepared(warm_states):
    p = warmed(warm_states)
    as_of = trigger(p)
    prefix = {s: [bar(as_of - 300, 365, open=350, high=380, low=340)] for s in SYMBOLS}
    return p, as_of, prefix


def path(t, low=364, high=366):
    return [{'start': t, 'bars': {s: dict(open=365, high=high, low=low, close=365) for s in SYMBOLS}}]


def test_pending_enters_and_stop_first_matches_original(warm_states):
    p, t, prefix = prepared(warm_states)
    state = deepcopy(p.snapshot())
    before = digest(state)
    result = evaluate_path(p.policy, RULES, state, path(t, low=1, high=1000),
                           as_of=t, historical_high_watermark=10000, hour_prefix=prefix)
    direct = CandidatePortfolio(p.policy, RULES)
    direct.restore(deepcopy(state))
    direct.on_closed_batch({s: bar(t, 365, low=1, high=1000) for s in SYMBOLS}, {}, t + 300)
    assert result['trades'] == direct.trades
    assert result['trades'] and all(x['exit_reason'] == 'stop' for x in result['trades'])
    assert digest(state) == before
    assert not any(x.get('reason') == 'entries_suppressed' for x in result['events'])
    for tr in result['trades']:
        assert tr['risk_amount'] == pytest.approx(tr['quantity'] * tr['unit_net_risk'])


def test_open_exposure_not_forced_closed_at_short_path_end(warm_states):
    p, t, prefix = prepared(warm_states)
    result = evaluate_path(p.policy, RULES, p.snapshot(), path(t), as_of=t,
                           historical_high_watermark=10000, hour_prefix=prefix)
    assert result['remaining_positions'] > 0
    assert not result['terminal_liquidation_forced']
    assert result['admission'] == 'ABSTAIN'


def test_new_reservation_suppressed_without_removing_old():
    p = ExistingExposurePortfolio(load_policy(candidate='A'), RULES)
    p.pending['BTCUSDT'] = {'sentinel': True}
    p._reserve('ETHUSDT', {}, 300)
    assert p.pending == {'BTCUSDT': {'sentinel': True}}


def test_missing_prefix_or_joint_symbol_rejected(warm_states):
    p, t, prefix = prepared(warm_states)
    with pytest.raises(ValueError, match='prefix'):
        evaluate_path(p.policy, RULES, p.snapshot(), path(t), as_of=t, historical_high_watermark=10000)
    bad = path(t)
    del bad[0]['bars']['SOLUSDT']
    with pytest.raises(ValueError, match='joint path'):
        evaluate_path(p.policy, RULES, p.snapshot(), bad, as_of=t,
                      historical_high_watermark=10000, hour_prefix=prefix)


def test_midnight_opening_gap_uses_original_clock(warm_states):
    p, t, _ = prepared(warm_states)
    while t % 86400:
        p.on_closed_batch({s: bar(t, 365) for s in SYMBOLS}, {}, t + 300)
        t += 300
    assert p.positions
    opening = [{'start': t, 'bars': {s: dict(open=370, high=371, low=369, close=370) for s in SYMBOLS}}]
    result = evaluate_path(p.policy, RULES, p.snapshot(), opening, as_of=t,
                           historical_high_watermark=max(10000, p.value()))
    assert result['original_opening_resets'][0]['time'] == t
    direct = CandidatePortfolio(p.policy, RULES)
    direct.restore(deepcopy(p.snapshot()))
    direct.on_closed_batch({s: bar(t, 370, low=369, high=371) for s in SYMBOLS}, {}, t + 300)
    assert result['terminal_state']['cash'] == direct.cash
    assert result['terminal_state']['day_start'] == direct.day_start


@pytest.mark.parametrize('damage', ['mark', 'kernel', 'future', 'risk'])
def test_invalid_snapshot_cannot_be_silently_simulated(warm_states, damage):
    p, t, prefix = prepared(warm_states)
    state = deepcopy(p.snapshot())
    if damage == 'mark':
        del state['marks']['BTCUSDT']
    elif damage == 'kernel':
        del state['kernels']['BTCUSDT']
    elif damage == 'future':
        state['pending']['BTCUSDT']['available_at'] = t + 300
    else:
        state['pending']['BTCUSDT']['risk_amount'] *= 2
    with pytest.raises(ValueError):
        evaluate_path(p.policy, RULES, state, path(t), as_of=t,
                      historical_high_watermark=10000, hour_prefix=prefix)


def test_stress_keeps_paid_entry_and_base_r(warm_states):
    p, t, prefix = prepared(warm_states)
    p.on_closed_batch({s: bar(t, 365) for s in SYMBOLS}, {}, t + 300)
    for s in SYMBOLS:
        prefix[s].append(bar(t, 365))
    t += 300
    state = deepcopy(p.snapshot())
    results = [evaluate_path(p.policy, RULES, state, path(t, low=1, high=1000),
               as_of=t, historical_high_watermark=10000, hour_prefix=prefix,
               future_cost_multiplier=c) for c in (1, 2)]
    assert results[0]['initial_reference_equity'] == results[1]['initial_reference_equity']
    assert results[0]['initial_risk_budget'] == results[1]['initial_risk_budget']
    for normal, stress in zip(results[0]['trades'], results[1]['trades']):
        original = state['positions'][stress['symbol']]
        assert stress['entry_price'] == normal['entry_price'] == original['entry_price']
        assert stress['entry_fee'] == original['entry_fee']
        assert stress['risk_amount'] == normal['risk_amount']
        assert stress['fees'] == pytest.approx(original['entry_fee'] + stress['quantity'] * stress['exit_price'] * p.fee * 2)
        assert stress['net_pnl'] < normal['net_pnl']
        assert stress['net_r'] == pytest.approx(stress['net_pnl'] / original['risk_amount'])
    assert results[0]['trades']


@pytest.mark.parametrize('cost', [0, 3, True])
def test_unregistered_future_cost_rejected(warm_states, cost):
    p, t, prefix = prepared(warm_states)
    with pytest.raises(ValueError, match='Future stress'):
        evaluate_path(p.policy, RULES, p.snapshot(), path(t), as_of=t,
                      historical_high_watermark=10000, hour_prefix=prefix, future_cost_multiplier=cost)


def test_omitting_unused_terminal_serialization_does_not_change_risk(warm_states):
    p, t, prefix = prepared(warm_states)
    state = deepcopy(p.snapshot())
    before = digest(state)
    full = evaluate_path(p.policy, RULES, state, path(t), as_of=t,
                         historical_high_watermark=10000, hour_prefix=prefix)
    compact = evaluate_path(p.policy, RULES, state, path(t), as_of=t,
                            historical_high_watermark=10000, hour_prefix=prefix, include_terminal_state=False)
    assert compact['terminal_state'] is None
    for key in ('risk', 'curve', 'trades', 'events'):
        assert compact[key] == full[key]
    assert digest(state) == before


def test_risk_budget_retains_pending_cash_and_original_risk_basis(warm_states):
    p, t, prefix = prepared(warm_states)
    state = deepcopy(p.snapshot())
    result = evaluate_path(p.policy, RULES, state, path(t), as_of=t,
                           historical_high_watermark=12000, hour_prefix=prefix)
    budget = result['initial_risk_budget']
    expected = sum(e['estimated_risk_amount'] for e in state['pending'].values())
    assert budget['sizing_risk_used'] == pytest.approx(expected)
    assert budget['pending_cash_reserved'] == pytest.approx(sum(e['reserved_cash'] for e in state['pending'].values()))
    assert budget['cash_unreserved'] + budget['pending_cash_reserved'] == pytest.approx(state['cash'])
    assert budget['open_risk_remaining_signed'] == pytest.approx(p.value() * p.policy['max_open_risk'] - expected)
    assert budget['daily_loss_line'] == pytest.approx(state['day_start'] * (1 - p.policy['daily_loss_limit']))
    assert budget['historical_high_watermark'] == 12000
    assert not budget['entry_permission']


def test_risk_budget_does_not_hide_existing_deficit(warm_states):
    from kquant_crypto.hybrid_mc_portfolio_v12 import risk_budget_audit
    p, t, _ = prepared(warm_states)
    for e in p.pending.values():
        e['estimated_risk_amount'] = 1000
    budget = risk_budget_audit(p, t, 12000)
    assert budget['open_risk_remaining_signed'] < 0
    assert not budget['entry_permission']
