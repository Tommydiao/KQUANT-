import pytest
from kquant_crypto.hybrid_target_contract import ResearchTarget,require_research_target,holding_identity
from kquant_crypto.hybrid_target_contract import interval_components


def test_population_cannot_be_consumed_as_trade_probability():
    with pytest.raises(ValueError):require_research_target(ResearchTarget.POPULATION,ResearchTarget.ENTRY,'offline_diagnostic')


def test_dev_artifact_cannot_activate_runtime():
    with pytest.raises(ValueError):require_research_target(ResearchTarget.ENTRY,ResearchTarget.ENTRY,'execution')
    assert require_research_target(ResearchTarget.POPULATION,ResearchTarget.POPULATION,'offline_diagnostic')['probability_name']=='p_gross_positive'


def fixture():
    t=dict(trade_id='t',symbol='ETH',mode='UP_TREND',policy_hash='p',signal_time=0,entry_time=0,exit_time=600,base_unit_net_risk=10)
    r=dict(trade_id='t',symbol='ETH',execution_policy_id='p',as_of=300,available_at=300,label_available_at=900,
           holding_features=dict(age_seconds=300,base_unit_net_risk=10,mark_to_entry_r=.1))
    return r,t


def test_same_economic_group_different_policy_parent():
    r,t=fixture();a=holding_identity(r,t)
    r.update(trade_id='t2',execution_policy_id='p2');t.update(trade_id='t2',policy_hash='p2')
    assert holding_identity(r,t)['economic_key']==a['economic_key']


def test_future_feature_rejected():
    r,t=fixture();r['holding_features']['future_mfe']=1
    with pytest.raises(ValueError):holding_identity(r,t)


def test_early_label_rejected():
    r,t=fixture();r['label_available_at']=300
    with pytest.raises(ValueError):holding_identity(r,t)


def test_transitive_overlap_across_symbols_and_boundary_touch():
    groups=[dict(economic_key=[s],information_start=a,information_end=b) for s,a,b in [('A',0,10),('B',8,20),('C',20,22),('D',30,40)]]
    result=interval_components(groups)
    assert len(result)==2
    assert result[0]['economic_keys']==[['A'],['B'],['C']]
    assert result[0]['information_end']==22
