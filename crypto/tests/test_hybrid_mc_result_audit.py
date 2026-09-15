import pytest
from kquant_crypto.hybrid_mc_result_audit import summarize_path_events
from kquant_crypto.hybrid_mc_result_audit import verify_numeric_summary


def test_numeric_summary_independently_checked():
    rows=[dict(net_change=v,max_historical_nav_drawdown=.2,
        max_incremental_nav_drawdown=.1,open_at_horizon=0) for v in (0,10,20)]
    report=dict(net_change_quantiles=[2,10,18],max_historical_nav_drawdown=.2,
        max_incremental_nav_drawdown=.1,open_at_horizon_paths=0)
    assert verify_numeric_summary(rows,report)==report
    report['net_change_quantiles'][1]=11
    with pytest.raises(ValueError,match='mismatch'):verify_numeric_summary(rows,report)


def test_numeric_summary_rejects_nonfinite_and_wrong_count():
    row=dict(net_change=1,max_historical_nav_drawdown=.2,
        max_incremental_nav_drawdown=.1,open_at_horizon=0)
    report=dict(net_change_quantiles=[1,1,1],max_historical_nav_drawdown=.2,
        max_incremental_nav_drawdown=.1,open_at_horizon_paths=1)
    with pytest.raises(ValueError,match='count'):verify_numeric_summary([row],report)
    row['net_change']=float('nan')
    with pytest.raises(ValueError,match='Nonfinite'):verify_numeric_summary([row],report)


def row(**kwargs):
    return dict(budget_exceeded=False,exit_reasons={},open_at_horizon=0,**kwargs)


def test_zero_count_is_not_zero_risk():
    r=summarize_path_events([row() for _ in range(5000)],5000)
    assert r['events']['budget_exceeded']['zero_event_upper95_if_iid']==pytest.approx(.000598967002)
    assert not r['calibrated_market_probability']


def test_partial_rejected_and_horizon_open_is_separate():
    with pytest.raises(ValueError):summarize_path_events([row()],5000)
    a=row();a.update(open_at_horizon=1,exit_reasons={'gap_stop':1})
    r=summarize_path_events([a],1)
    assert r['events']['protective_stop']['count']==1
    assert r['events']['open_at_horizon']['zero_event_upper95_if_iid'] is None
