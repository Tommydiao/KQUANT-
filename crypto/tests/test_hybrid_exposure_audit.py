import pytest
from kquant_crypto.hybrid_exposure_audit import exposure_audit


def test_union_time_and_sum_position_time_differ():
    trades=[dict(trade_id='a',symbol='A',entry_time=0,exit_time=600,net_pnl=2),
            dict(trade_id='b',symbol='B',entry_time=300,exit_time=900,net_pnl=-3)]
    marks=[dict(time=t,equity=100,cash=80) for t in (0,300,600,900)]
    r=exposure_audit(trades,marks,0,900,['A','B'])
    assert r['any_position_seconds']==900 and r['summed_position_seconds']==1200
    assert r['net_pnl_excluding_best_net_asset']==-3
    assert r['time_weighted_costed_position_value_fraction']==pytest.approx(.2)


def test_gap_not_interpolated_and_duplicates_rejected():
    marks=[dict(time=t,equity=100,cash=100) for t in (0,300,900)]
    r=exposure_audit([],marks,0,900,['A'])
    assert r['valuation_covered_seconds']==300
    assert r['valuation_gaps']==[[300,900]]
    with pytest.raises(ValueError):exposure_audit([],marks+marks[-1:],0,900,['A'])


def test_untraded_asset_cannot_be_best_performer():
    trades=[dict(trade_id='a',symbol='A',entry_time=0,exit_time=300,net_pnl=-2)]
    marks=[dict(time=t,equity=100,cash=100) for t in (0,300)]
    r=exposure_audit(trades,marks,0,300,['A','B'])
    assert r['best_net_asset']=='A' and r['missing_traded_symbols']==['B']
