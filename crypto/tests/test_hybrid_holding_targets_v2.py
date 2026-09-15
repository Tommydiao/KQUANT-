from types import SimpleNamespace

import pytest

from kquant_crypto.hybrid_holding_targets_v2 import holding_target_v2


def trade():
    return dict(entry_time=0, exit_time=900, entry_price=100., exit_price=105.,
        base_unit_net_risk=2., quantity=1., entry_fee=.1, fees=.205,
        cost_multiplier=1, fee_bps=10, execution_source='ohlcv',
        trade_id='id', path_unverifiable=False, exit_reason='stop', policy_hash='frozen')


def run(t=None, cutoff=1200, complete=True):
    return holding_target_v2(t or trade(), SimpleNamespace(start=0, close=102),
        SimpleNamespace(start=300, open=103), cutoff=cutoff, policy='T1', path_complete=complete)


def test_exit_bar_must_close_before_label_matures():
    assert run(cutoff=900)['label_status'] == 'CENSORED'
    assert run(cutoff=1199)['continue_minus_exit_r'] is None
    mature = run()
    assert mature['label_available_at'] == 1200
    assert mature['continue_minus_exit_r'] == pytest.approx((105 - 103 * .9995) * .999 / 2)
    assert not mature['new_trade']
    assert 'exit_price' not in mature['holding_features']


def test_path_gap_never_zero_or_a_mature_result():
    row = run(complete=False)
    assert row['label_status'] == 'UNAVAILABLE'
    assert row['continue_minus_exit_r'] is None


def test_frozen_r_not_changed_by_trailing_stop():
    t = trade()
    t['stop'] = 103
    t['unit_net_risk'] = .25
    assert run(t)['continue_minus_exit_r'] == run()['continue_minus_exit_r']


def test_fee_conflict_rejected():
    t = trade()
    t['fees'] *= 2
    with pytest.raises(ValueError):
        run(t)
