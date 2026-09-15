import pytest
from kquant_crypto.candidate_policy import load_policy
from kquant_crypto.candidate_simulation import CandidatePortfolio
from kquant_crypto.hybrid_research_portfolio import ResearchPortfolio


def test_replaced_exits_never_disable_protection(monkeypatch):
    p=ResearchPortfolio(load_policy(candidate='A'),{},exit_candidate='T1')
    p.positions['BTCUSDT']={'mode':'UP_TREND'}
    calls=[]
    monkeypatch.setattr(CandidatePortfolio,'_exit',lambda self,s,r,t,reason:calls.append(reason))
    for reason in ('target','gap_target','timeout','mode_invalidated'):
        p._exit('BTCUSDT',100,0,reason)
    assert calls==[]
    for reason in ('stop','gap_stop','entry_gap_stop','daily_loss','data_gap','terminal_liquidation','structure_invalidated'):
        p._exit('BTCUSDT',100,0,reason)
    assert len(calls)==7
    p.positions['BTCUSDT']['mode']='RANGE'
    p._exit('BTCUSDT',100,0,'timeout')
    assert calls[-1]=='timeout'


def test_checkpoint_cannot_restore_into_original_policy():
    policy=load_policy(candidate='A')
    p=ResearchPortfolio(policy,{},exit_candidate='T1')
    state=p.snapshot()
    q=ResearchPortfolio(policy,{},exit_candidate='T1')
    q.restore(state)
    assert q.snapshot()==state
    with pytest.raises(ValueError):
        CandidatePortfolio(policy,{}).restore(state)
    with pytest.raises(ValueError):
        ResearchPortfolio(policy,{},exit_candidate='T2').restore(state)
    with pytest.raises(ValueError):
        p.on_quote('BTCUSDT',100,101,1)
