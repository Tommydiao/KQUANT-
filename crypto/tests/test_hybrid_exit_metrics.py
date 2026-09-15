from kquant_crypto.hybrid_exit_metrics import summarize


def test_overlap_and_net_statistics():
    rows=[dict(net_r=2,fixed_path_stress_net_r=1,entry_time=0,exit_time=7200),
          dict(net_r=-1,fixed_path_stress_net_r=-2,entry_time=3600,exit_time=10800)]
    result=summarize(rows)
    assert result['profit_factor']==2 and result['payoff']==2
    assert result['same_path_stress_pf']==.5
    assert result['overlapping_pairs']==1
    assert result['portfolio_risk_validated'] is False


def test_empty_not_zero_performance():
    assert summarize([])['mean_net_r'] is None
