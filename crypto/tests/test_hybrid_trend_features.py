import pytest
from kquant_crypto.strategy_dual_mode_v1 import Bar, _Indicators
from kquant_crypto.hybrid_trend_features import TrendFeatures


def test_stream_matches_baseline_and_resets_gap():
    stream, baseline = TrendFeatures(), _Indicators()
    for i in range(250):
        bar = Bar(i*3600,100+i,102+i,99+i,101+i,10)
        baseline.update(bar,hourly=True)
        row = stream.update(bar,(i+1)*3600)
    assert row['status']=='AVAILABLE'
    assert row['values']['ema50_slope3_atr']==baseline.slope/baseline.atr
    assert row['values']['positive_close_fraction24']==1
    with pytest.raises(ValueError):
        stream.update(bar,250*3600)
    assert stream.update(Bar(251*3600,350,352,349,351,10),252*3600)['status']=='WARMUP'


def test_forming_bar_rejected():
    with pytest.raises(ValueError):
        TrendFeatures().update(Bar(0,100,101,99,100,1),3599)
