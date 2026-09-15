from kquant_crypto.hybrid_multifactor_labels import opportunity_label
from kquant_crypto.strategy_dual_mode_v1 import Bar


def rows():
    return [Bar(i*3600,100,110,90,105,20) for i in range(30)]


def test_end_boundary_and_no_trade_claim():
    bars=rows(); starts=[b.start for b in bars]
    result=opportunity_label(bars,starts,3600,100,6,7*3600)
    assert result['label_status']=='MATURE'
    assert result['label_available_at']==7*3600
    assert result['fill_status']=='NOT_APPLICABLE'
    assert abs(result['gross_return']-.05)<1e-10
    censored=opportunity_label(bars,starts,3600,100,6,6*3600)
    assert censored['label_status']=='CENSORED'
    assert censored['gross_return'] is None


def test_gap_and_future_after_window():
    bars=rows(); starts=[b.start for b in bars]
    original=opportunity_label(bars,starts,3600,100,6,30*3600)
    bars[-1]=Bar(29*3600,100,10000,1,300,20)
    assert opportunity_label(bars,starts,3600,100,6,30*3600)==original
    del bars[3]
    assert opportunity_label(bars,[b.start for b in bars],3600,100,6,30*3600)['label_status']=='UNAVAILABLE'
