from kquant_crypto.strategy_dual_mode_v1 import Bar
from kquant_crypto.hybrid_reference_returns import six_hour_return


def bars():return [Bar(i*300,100,102,99,101,1) for i in range(72)]


def test_fixed_horizon_costs_once_and_future_ignored():
    data=bars();r=six_hour_return(0,data,21600)
    assert abs(r['gross_return']-.01)<1e-10
    assert r==six_hour_return(0,data+[Bar(21600,101,999,1,999,1)],21600)
    assert r['net_return']<r['gross_return'] and not r['stops_applied']


def test_gap_or_cutoff_not_zero():
    assert six_hour_return(0,bars()[:-1],21600)['net_return'] is None
    assert six_hour_return(0,bars(),21000)['status']=='CENSORED'
