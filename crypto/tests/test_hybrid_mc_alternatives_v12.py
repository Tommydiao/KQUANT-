from copy import deepcopy
import math

import pytest

from test_candidate_portfolio import warm_states, warmed, bar, SIGNAL_START, SYMBOLS, RULES
from kquant_crypto.hybrid_mc_portfolio_v12 import ExistingExposurePortfolio
from kquant_crypto.hybrid_mc_portfolio_v12 import evaluate_path
from kquant_crypto.hybrid_mc_alternatives_v12 import prepare_alternatives, MULTIPLIERS
from kquant_crypto.candidate_policy import digest


def proposal_state(warm_states):
    p = warmed(warm_states, portfolio_class=ExistingExposurePortfolio)
    b = bar(SIGNAL_START, 365, open=350, high=380, low=340)
    p.on_closed_batch({s: b for s in SYMBOLS}, {}, SIGNAL_START + 300)
    assert not p.pending
    return p, SIGNAL_START + 300


def test_registered_multipliers_do_not_choose_or_upsize(warm_states):
    p, t = proposal_state(warm_states)
    state = deepcopy(p.snapshot())
    result = prepare_alternatives(p.policy, RULES, state, 'BTCUSDT', as_of=t)
    assert [a['multiplier'] for a in result['alternatives']] == list(MULTIPLIERS)
    base = result['alternatives'][-1]['quantity']
    assert base > 0 and result['selected'] is None
    for a in result['alternatives']:
        assert a['quantity'] <= base * a['multiplier'] + 1e-12
        assert not a['selected']
    assert digest(state) == result['original_state_hash']
    assert result['alternatives'][0]['state'] == state


def test_zero_keeps_already_pending_and_original_budget(warm_states):
    p, t = proposal_state(warm_states)
    btc = prepare_alternatives(p.policy, RULES, p.snapshot(), 'BTCUSDT', as_of=t)['alternatives'][-1]['state']
    result = prepare_alternatives(p.policy, RULES, btc, 'ETHUSDT', as_of=t)
    assert result['alternatives'][0]['state'] == btc
    for a in result['alternatives']:
        assert a['state']['pending']['BTCUSDT'] == btc['pending']['BTCUSDT']
        assert a['state']['day_start'] == btc['day_start']
        assert a['state']['cash'] == btc['cash']


def test_existing_symbol_cannot_be_treated_as_new_proposal(warm_states):
    p, t = proposal_state(warm_states)
    state = prepare_alternatives(p.policy, RULES, p.snapshot(), 'BTCUSDT', as_of=t)['alternatives'][-1]['state']
    result = prepare_alternatives(p.policy, RULES, state, 'BTCUSDT', as_of=t)
    assert all(a['quantity'] == 0 for a in result['alternatives'])
    assert all(a['state'] == state for a in result['alternatives'])


def test_late_or_modified_plan_rejected(warm_states):
    p, t = proposal_state(warm_states)
    state = deepcopy(p.snapshot())
    with pytest.raises(ValueError):
        prepare_alternatives(p.policy, RULES, state, 'BTCUSDT', as_of=t + 300)
    state['decisions']['BTCUSDT']['signal']['unit_net_risk'] *= 2
    with pytest.raises(ValueError, match='BASE'):
        prepare_alternatives(p.policy, RULES, state, 'BTCUSDT', as_of=t)


def test_small_alternatives_skip_instead_of_rounding_up(warm_states):
    p, t = proposal_state(warm_states)
    base = prepare_alternatives(p.policy, RULES, p.snapshot(), 'BTCUSDT', as_of=t)['alternatives'][-1]['quantity']
    rules = deepcopy(RULES)
    rules['BTCUSDT']['min_qty'] = math.ceil(base * .75 / .001) * .001
    p.rules = rules  # Synthetic rule fixture; snapshot binds this exact rule hash.
    result = prepare_alternatives(p.policy, rules, p.snapshot(), 'BTCUSDT', as_of=t)
    assert result['alternatives'][1]['status'] == 'SKIP_MINIMUM_ORDER'
    assert result['alternatives'][2]['status'] == 'SKIP_MINIMUM_ORDER'
    assert result['alternatives'][3]['quantity'] == base


@pytest.mark.parametrize('cost', [1, 2])
def test_same_path_alternatives_keep_existing_risk(warm_states, cost):
    p, t = proposal_state(warm_states)
    existing = prepare_alternatives(p.policy, RULES, p.snapshot(), 'BTCUSDT', as_of=t)['alternatives'][-1]['state']
    alternatives = prepare_alternatives(p.policy, RULES, existing, 'ETHUSDT', as_of=t)['alternatives']
    prefix = {s: [bar(SIGNAL_START, 365, open=350, high=380, low=340)] for s in SYMBOLS}
    common = [{'start': t, 'bars': {s: dict(open=365, high=1000, low=1, close=365) for s in SYMBOLS}}]
    outputs = [evaluate_path(p.policy, RULES, a['state'], common, as_of=t,
               historical_high_watermark=10000, hour_prefix=prefix, future_cost_multiplier=cost) for a in alternatives]
    original_trade = outputs[0]['trades'][0]
    assert original_trade['symbol'] == 'BTCUSDT'
    for output in outputs:
        assert output['trades'][0] == original_trade
        assert output['admission'] == 'ABSTAIN'
    assert len(outputs[0]['trades']) == 1
    assert len(outputs[-1]['trades']) == 2


def test_zero_quantity_cannot_erase_preexisting_daily_loss(warm_states):
    p, t = proposal_state(warm_states)
    state = deepcopy(p.snapshot())
    # Synthetic prior day equity exceeds current cash; no policy threshold changes.
    state['day_start'] = 11000
    original = digest(state)
    variants = prepare_alternatives(p.policy, RULES, state, 'BTCUSDT', as_of=t)['alternatives']
    zero = variants[0]
    assert zero['multiplier'] == 0 and zero['state'] == state
    prefix = {s: [bar(SIGNAL_START, 365, open=350, high=380, low=340)] for s in SYMBOLS}
    common = [{'start': t, 'bars': {s: dict(open=365, high=365, low=365, close=365) for s in SYMBOLS}}]
    output = evaluate_path(p.policy, RULES, zero['state'], common, as_of=t,
                           historical_high_watermark=11000, hour_prefix=prefix)
    assert output['risk']['daily_loss_line_breached']
    assert output['risk']['absolute_high_watermark_drawdown'] > 0
    assert output['risk']['incremental_peak_drawdown'] == 0
    assert output['admission'] == 'ABSTAIN'
    assert digest(state) == original
