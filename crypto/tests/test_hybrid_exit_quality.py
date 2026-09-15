import pytest
from kquant_crypto.strategy_dual_mode_v1 import Bar
from kquant_crypto.hybrid_exit_quality import exit_quality


def trade():
    return {'entry_time': 0, 'exit_time': 600, 'execution_source': 'ohlcv',
            'base_unit_net_risk': 10., 'quantity': 1., 'entry_price': 100.,
            'entry_fee': .1, 'fee_bps': 10., 'execution_cost_bps': 5., 'net_r': -.5}


def test_costed_peak_and_exit_bar_future_excluded():
    bars = [Bar(0,100,120,99,110,1), Bar(300,110,120,90,100,1), Bar(600,100,999,1,999,1)]
    result = exit_quality(trade(), bars, 900)
    expected = (110*.9995*.999-100.1)/10
    assert result['observed_peak_net_r'] == pytest.approx(expected)
    assert result['giveback_net_r'] == pytest.approx(expected+.5)
    assert result['capture_of_observed_peak'] < 0
    assert result['feature_eligible'] is False
    assert result['base_unit_net_risk'] == 10


def test_missing_holding_bar_is_not_zero_and_cutoff_enforced():
    assert exit_quality(trade(), [], 900)['status'] == 'UNAVAILABLE'
    with pytest.raises(ValueError):
        exit_quality(trade(), [], 300)
