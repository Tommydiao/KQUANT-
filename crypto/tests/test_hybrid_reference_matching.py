import pytest
from kquant_crypto.hybrid_reference_matching import select_reference


def signal():return dict(symbol='ETH',mode='UP_TREND',as_of=7200,available_at=7200,atr_fraction=.01,economic_signal_id='s')
def row(time=3600,**kw):return dict(dict(symbol='ETH',mode='UP_TREND',as_of=time,available_at=time,atr_fraction=.01),**kw)


def test_future_or_outcome_fields_cannot_choose_reference():
    s=signal();a=row();r=select_reference(s,[a],set())
    assert select_reference(s,[a,row(10800)],set())==r
    assert r['reference']['as_of']==3600


def test_no_relaxation_for_missing_controls():
    assert select_reference(signal(),[row(atr_fraction=.02)],set())['status']=='UNMATCHED'
    assert select_reference(signal(),[row()],{('ETH',3600)})['status']=='UNMATCHED'


def test_unavailable_and_duplicate_snapshots():
    assert select_reference(signal(),[row(available_at=4000)],set())['status']=='UNMATCHED'
    with pytest.raises(ValueError):select_reference(signal(),[row(),row()],set())
