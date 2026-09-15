from types import SimpleNamespace
import pytest
from kquant_crypto.hybrid_holding_targets import holding_target


def trade():
    return dict(entry_time=0, exit_time=900, entry_price=100, exit_price=105,
                unit_net_risk=2, trade_id='a', exit_reason='target')


def test_paired_target_frozen_r_and_timing():
    row = holding_target(trade(), SimpleNamespace(start=0, close=102),
                         SimpleNamespace(start=300, open=103), cutoff=900)
    assert row['continue_minus_exit_r'] == pytest.approx((105-103*.9995)*.999/2)
    assert row['label_available_at'] == 900
    assert row['as_of'] == 300 and not row['new_trade']
    assert 'exit_price' not in row['holding_features']


def test_gap_and_censor_never_zero():
    bar = SimpleNamespace(start=0, close=102)
    assert holding_target(trade(), bar, None, cutoff=900)['continue_minus_exit_r'] is None
    assert holding_target(trade(), bar, None, cutoff=600)['label_status'] == 'CENSORED'
    with pytest.raises(ValueError):
        holding_target(trade(), SimpleNamespace(start=600, close=102), None, cutoff=900)
