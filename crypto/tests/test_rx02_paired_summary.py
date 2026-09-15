import pytest
from scripts.summarize_rx02_paired_dev import paired_summary


def rows():
    return [dict(candidate=c,economic_signal_id='s',net_r=v,reason='stop') for c,v in [('ORIGINAL',-1),('T1',-.5),('T2',-2)]]


def test_paired_delta_not_challenger_subset_mean():
    r=paired_summary(rows())
    assert r['T1']['mean_paired_delta']==.5
    assert r['T2']['paired_worsened']==1


def test_missing_outcome_stays_missing():
    data=rows();data[1]['net_r']=None
    assert paired_summary(data)['T1']['paired_count']==0
    assert paired_summary(data)['T1']['mean_paired_delta'] is None


def test_unmatched_or_duplicate_rejected():
    with pytest.raises(ValueError):paired_summary(rows()[:-1])
    with pytest.raises(ValueError):paired_summary(rows()+rows()[:1])
