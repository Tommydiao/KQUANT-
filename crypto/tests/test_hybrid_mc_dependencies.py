import pytest
from kquant_crypto.hybrid_mc_dependencies import audit_dependencies


def item(t, key=None):
    return dict(as_of=t,history_start=t-100,scenario_end=t+50,economic_keys=[key] if key else [])


def test_transitive_windows_remain_grouped():
    result=audit_dependencies([item(1000),item(1140),item(1280),item(2000)])
    assert result['components']==[[1000,1140,1280],[2000]]
    assert result['independent_sample_count'] is None


def test_same_economic_position_connects_nonoverlapping_windows():
    key=['ETHUSDT','UP_TREND',900]
    result=audit_dependencies([item(1000,key),item(2000,key)])
    assert result['components']==[[1000,2000]]
    assert result['edges'][0]['reasons']==['SAME_ECONOMIC_POSITION_OR_PENDING']


def test_invalid_identity_or_interval_rejected():
    with pytest.raises(ValueError): audit_dependencies([item(1000),item(1000)])
    row=item(1000);row['history_start']=1001
    with pytest.raises(ValueError): audit_dependencies([row])
