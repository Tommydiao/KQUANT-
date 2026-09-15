from copy import deepcopy
import pytest
from kquant_crypto.hybrid_prospective_risk import closed_hours,paired_states,simulate_pair
from kquant_crypto.candidate_policy import load_policy
from kquant_crypto.hybrid_research_portfolio import ResearchPortfolio
from kquant_crypto.strategy_dual_mode_v1 import Bar


def prefix():
    return [dict(start=t,bars={'BTCUSDT':dict(start=t,open=100,high=101,low=99,close=100,available_at=t+300)}) for t in range(0,3300,300)]


def test_partial_first_hour_uses_closed_history():
    result=list(closed_hours(3300,prefix(),[{'BTCUSDT':Bar(3300,100,105,98,104,0)}],['BTCUSDT']))
    hour=result[0][1]['BTCUSDT']
    assert (hour.start,hour.open,hour.high,hour.low,hour.close)==(0,100,105,98,104)


def test_missing_future_or_late_prefix_rejected():
    with pytest.raises(ValueError):list(closed_hours(3300,prefix()[:-1],[],['BTCUSDT']))
    late=prefix();late[-1]['bars']['BTCUSDT']['available_at']=3301
    with pytest.raises(ValueError):list(closed_hours(3300,late,[],['BTCUSDT']))
    with pytest.raises(ValueError):list(closed_hours(3600,prefix(),[],['BTCUSDT']))


def test_generated_gap_rejected():
    with pytest.raises(ValueError):list(closed_hours(3600,[],[{'BTCUSDT':Bar(3900,100,101,99,100,0)}],['BTCUSDT']))


def test_cancel_only_target_no_cash_refund_and_no_mutation():
    state=dict(cash=100,pending={'BTCUSDT':dict(signal_time=300,quantity=1),
        'ETHUSDT':dict(signal_time=300,quantity=2)},positions={})
    original=deepcopy(state);yes,no=paired_states(state,'BTCUSDT',300)
    assert state==original and yes==state
    assert no['cash']==100 and no['pending']=={'ETHUSDT':state['pending']['ETHUSDT']}
    yes['pending']['BTCUSDT']['quantity']=9
    assert state==original
    with pytest.raises(ValueError):paired_states(state,'SOLUSDT',300)
    with pytest.raises(ValueError):paired_states(state,'BTCUSDT',600)


def test_real_original_entry_events_and_other_pending_preserved():
    policy=load_policy(candidate='A')
    rules={s:dict(step_size=.001,min_qty=.001,min_notional=1) for s in policy['symbols']}
    p=ResearchPortfolio(policy,rules,exit_candidate='ORIGINAL')
    for symbol in ('BTCUSDT','ETHUSDT'):
        p.decisions[symbol]={'available_at':3600}
        p._reserve(symbol,dict(mode='UP_TREND',entry_reference=100,stop=90,target=120,unit_net_risk=10),3600)
    state=p.snapshot();before=deepcopy(state)
    path={'batches':[{s:Bar(3600,100,101,99,100,0) for s in policy['symbols']}]}
    result=simulate_pair(state,dict(as_of=3600,first_hour_prefix=[]),path,policy,rules,'ORIGINAL','BTCUSDT')
    assert state==before
    assert result['results']['WITH_PLAN']['target_plan_fills']==1
    assert result['results']['WITHOUT_PLAN']['target_plan_fills']==0
    assert result['results']['WITH_PLAN']['open_at_horizon']==2
    assert result['results']['WITHOUT_PLAN']['open_at_horizon']==1
