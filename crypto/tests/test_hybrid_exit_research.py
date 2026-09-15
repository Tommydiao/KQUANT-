import pytest
from kquant_crypto.strategy_dual_mode_v1 import Bar
from kquant_crypto.hybrid_exit_research import structural_exit, net_target_reference


def test_target_is_net_of_costs():
    for multiple in (2.5,3.):
        reference = net_target_reference(100,2,multiple)
        sell = reference*.9995
        assert (sell-100-.001*(sell+100))/2 == pytest.approx(multiple)


def test_protection_only_tightens_future_ignored_and_range_unchanged():
    hours = [Bar(i*3600,100,103,98,101,1) for i in range(7)]
    result = structural_exit('T2','UP_TREND',hours,7*3600,95,4)
    assert result['stop_next_bar']==97
    assert structural_exit('T2','UP_TREND',hours,7*3600,99,4)['stop_next_bar']==99
    future = Bar(7*3600,1,2,1,1,1)
    assert structural_exit('T2','UP_TREND',hours+[future],7*3600,95,4)==result
    assert structural_exit('T2','RANGE',hours,7*3600,95,4)['stop_next_bar']==95


def test_breach_uses_previous_six_hours_and_closed_signal():
    hours = [Bar(i*3600,100,103,98,101,1) for i in range(6)]
    hours += [Bar(6*3600,100,101,95,97,1)]
    result = structural_exit('T1','UP_TREND',hours,7*3600,90,4)
    assert result['exit_next_bar'] and result['effective_at']==7*3600
    assert result['stop_next_bar']==90
    assert structural_exit('T1','UP_TREND',hours,7*3600-1,90,4)['status']=='UNAVAILABLE'
