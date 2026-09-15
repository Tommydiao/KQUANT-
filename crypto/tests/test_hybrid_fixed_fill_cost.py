import pytest
from kquant_crypto.hybrid_fixed_fill_cost import reprice_fixed_fill


def trade():
    return dict(trade_id='a',symbol='BTCUSDT',mode='UP_TREND',entry_time=1,exit_time=2,
        quantity=1,entry_market_reference=100,exit_market_reference=110,
        entry_price=100.05,exit_price=109.945,fees=.209995,net_pnl=9.685005,
        base_unit_net_risk=5,cost_multiplier=1,execution_source='ohlcv',fee_bps=10,
        ohlcv_execution_cost_bps=5,path_unverifiable=False)


def test_costs_recomputed_without_reducing_r_denominator():
    base=reprice_fixed_fill(trade(),1);stress=reprice_fixed_fill(trade(),2)
    assert base['net_pnl']==pytest.approx(9.685005)
    assert stress['net_pnl']==pytest.approx(9.37002)
    assert base['base_risk_cash']==stress['base_risk_cash']==5
    assert stress['quantity_and_timing_frozen']


def test_quote_and_existing_stress_fills_rejected():
    t=trade();t['execution_source']='quotes'
    with pytest.raises(ValueError):reprice_fixed_fill(t,2)
    t=trade();t['cost_multiplier']=2
    with pytest.raises(ValueError):reprice_fixed_fill(t,2)
