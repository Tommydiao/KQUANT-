import pytest
from kquant_crypto.hybrid_excursion_audit import audit_excursion
from kquant_crypto.strategy_dual_mode_v1 import Bar


def trade(reason='timeout'):
    return dict(entry_time=0,exit_time=600,execution_source='ohlcv',exit_reason=reason,
                base_unit_net_risk=10,quantity=1,entry_price=100,entry_fee=.1,
                fee_bps=10,execution_cost_bps=5,target=120,net_r=-.5)


def test_protection_bar_future_high_not_mfe_or_target():
    bars=[Bar(0,100,105,99,101,1),Bar(300,101,999,80,100,1)]
    r=audit_excursion(trade('stop'),bars,600)
    assert r['mfe_first_interval']==[0,300]
    assert r['net_mfe_observed']<1
    assert r['target_touch_status']=='EXIT_BAR_ORDER_UNRESOLVED'
    assert not r['feature_eligible']


def test_open_exit_excludes_following_bar_and_first_tie():
    bars=[Bar(0,100,125,99,101,1),Bar(300,101,125,98,100,1),Bar(600,100,999,1,1,1)]
    r=audit_excursion(trade(),bars,900)
    assert r['mfe_first_interval']==[0,300]
    assert r['mae_first_interval']==[300,600]
    assert r['target_touch_before_exit_interval']==[0,300]


def test_gap_and_out_of_authorization_fail_closed():
    assert audit_excursion(trade(),[],600)['status']=='UNAVAILABLE'
    with pytest.raises(ValueError):audit_excursion(trade(),[],300)


def test_retained_t1_target_not_an_active_exit():
    t=dict(trade(),strategy_version='hybrid_exit_research_dev_v1:T1',mode='UP_TREND')
    bars=[Bar(0,100,125,99,101,1),Bar(300,101,125,98,100,1)]
    r=audit_excursion(t,bars,600)
    assert r['target_reference'] is None
    assert r['retained_original_target_not_active']==120
    assert r['target_touch_status']=='NO_FIXED_TARGET'
