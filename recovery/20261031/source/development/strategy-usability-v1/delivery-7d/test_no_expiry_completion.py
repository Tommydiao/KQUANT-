from datetime import datetime, timezone
from types import SimpleNamespace
import pytest
from kquant import options_intraday_comparison as model
from kquant.options_opening_trend_pipeline import step

NOW=datetime(2026,10,16,13,35,10,tzinfo=timezone.utc)
def job():
    p=model.load_policy()
    return {'evaluation':{'policy_id':p['policy_id'],'policy_hash':p['policy_hash'],
        'symbol':'TEST','session':'2026-10-16','scope_hash':'scope','deadline_at':'2026-10-16T13:40:00+00:00'},
        'progress':{'phase':'EXPIRIES'}}

def test_no_matching_expiry_finishes_without_repeated_market_calls():
    value=job()
    services=SimpleNamespace(expiries=lambda symbol:{'provider_status':'available','expiries':['2026-10-30']})
    progress,done,revision=step(value,services,clock=lambda:NOW)
    assert not done and revision is None
    assert progress['collection_reason'] == 'NO_MATCHING_CALENDAR_DTE'
    assert progress['expiry_observation']['expiries'] == ['2026-10-30']
    assert progress['expiry_observation']['provider_receipt_time'] is None
    value['progress']=progress
    # No spot/current/event methods exist: known empty scope must not refresh them.
    _,done,revision=step(value,services,clock=lambda:NOW)
    assert done
    assert revision['reasons'] == ['NO_MATCHING_CALENDAR_DTE']
    assert revision['qualified_signal'] is False
    assert revision['research_only'] is True

@pytest.mark.parametrize('response',[{}, {'provider_status':'unavailable','expiries':[]}])
def test_unknown_response_is_not_no_matching_contract(response):
    with pytest.raises(RuntimeError,match='EXPIRY_SOURCE_UNAVAILABLE'):
        step(job(),SimpleNamespace(expiries=lambda s:response),clock=lambda:NOW)

def test_matching_expiry_keeps_existing_chain_path():
    progress,done,revision=step(job(),SimpleNamespace(expiries=lambda s:{
        'provider_status':'available','expiries':['2026-10-20']}),clock=lambda:NOW)
    assert progress['phase'] == 'CHAIN'
    assert progress['expiries'] == ['2026-10-20']
    assert not done and revision is None
