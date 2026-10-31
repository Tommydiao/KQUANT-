"""Synthetic transport, isolated original budget schema; no key or network access."""
from contextlib import closing
from copy import deepcopy
from datetime import UTC,datetime,timedelta
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

from bootstrap import activate,HERE
activate()
from kquant import options_research_ai as ai
from kquant import options_api_budget as budget
from kquant import options_llm_credentials as credentials


def fixture(tmp_path):
    config=json.loads((HERE/'config/research_ai.json').read_text())
    now=datetime(2026,10,31,15,tzinfo=UTC)
    receipt=dict(gate='O-SETUP',status='APPROVED',approved_by='OWNER',
        user_reply_id='TEST_ONLY_NOT_OWNER',approval_id='TEST_ONLY_WEEKEND',
        config_hash=ai.config_identity(config),approved_at='2026-10-31T14:00:00Z',
        authorization_total_usd='5',task_limit_usd='1',valid_until=config['valid_until'],
        capability_tests_allowed=True,live_paid_research_allowed=False)
    event=dict(event_id='TEST_ONLY_EVENT',input_revision=1,
        deadline_at=(now+timedelta(seconds=300)).isoformat(),
        bar_evidence=dict(open=10,high=12,low=9,close=11),option_cost={'cost':None})
    return config,receipt,event,now,tmp_path/'TEST_ONLY_copilot.sqlite3'


def output(request,*,tool=False,status='completed'):
    items=[{'type':'reasoning','id':'rs_TEST_ONLY','encrypted_content':'TEST_ONLY_encrypted',
        'summary':[]}] if tool else []
    if tool:
        items.append(dict(type='function_call',name='compute_price_components',
            arguments='{}',call_id='call_TEST_ONLY',id='fc_TEST_ONLY'))
    else:
        items.append(dict(type='message',content=[dict(type='output_text',text=json.dumps(dict(
            support_refs=['bar_evidence'],opposing_refs=[],missing_inputs=['cost'],
            review_reasons=['READ_ONLY_RESEARCH'])))]))
    return dict(id='resp_TEST_ONLY',model=request['model'],status=status,service_tier='default',
        output=items,usage=dict(input_tokens=100,output_tokens=100,
            output_tokens_details={'reasoning_tokens':80}))


def test_tool_roundtrip_encrypted_continuity_no_reasoning_log(tmp_path):
    config,receipt,event,now,path=fixture(tmp_path)
    requests=[]
    def transport(req):
        requests.append(req)
        return output(req,tool=len(requests)==1)
    client=ai.ResponsesResearchClient(config=config,receipt=receipt,budget_path=path,
        transport=transport,key_loader=lambda:None,clock=lambda:now)
    result=client.assess(event,test_only=True)
    assert result['state']=='COMPLETED',result
    assert result['actual_cost_usd']=='0.0024'
    assert requests[1]['input'][-1]['call_id']=='call_TEST_ONLY'
    assert any(x.get('encrypted_content')=='TEST_ONLY_encrypted' for x in requests[1]['input'])
    assert 'TEST_ONLY_encrypted' not in json.dumps(result)
    assert result['tools'][0]['payload']['M']==1/3
    assert result['versions']['prompt_version']==ai.PROMPT_VERSION
    assert result['review_envelope']['event_id']==event['event_id']
    assert result['review_envelope']['valid_until']==event['deadline_at']
    assert result['review_envelope']['review_state']=='REVALIDATION_REQUIRED'
    assert result['review_envelope']['bbo_freshness_extended'] is False
    assert not client.assess(event,test_only=True)['paid_call']


def test_dpapi_missing_never_uses_unknown_environment(tmp_path):
    with patch.object(credentials,'credential_path',return_value=tmp_path/'absent'),patch.dict(
            'os.environ',{'OPENAI_API_KEY':'TEST_ONLY_do_not_use'}):
        assert credentials.api_key()==''
        assert credentials.credential_source()=='MISSING_LOCAL_DPAPI'


def test_total_budget_persists_across_day_and_models(tmp_path):
    path=tmp_path/'TEST_ONLY_copilot.sqlite3'
    for i in range(5):
        with patch.object(budget,'_day',return_value='2026-10-31' if i<3 else '2026-11-01'):
            r=budget.reserve_api_budget(scan_id=str(i),worst_case_usd='1',daily_limit_usd='5',
                timezone='Asia/Shanghai',approved=True,approval_id='TEST_ONLY',approval_total_usd='5',
                candidate_id=str(i),task_limit_usd='1',role='SOL' if i%2 else 'ASTRA',store_path=path)
            assert r['paid_call_allowed']
            budget.settle_api_budget(r['reservation_id'],actual_cost_usd=None,request_sent=True,store_path=path)
    with patch.object(budget,'_day',return_value='2026-11-01'):
        r=budget.reserve_api_budget(scan_id='six',worst_case_usd='.01',daily_limit_usd='5',
            timezone='Asia/Shanghai',approved=True,approval_id='TEST_ONLY',approval_total_usd='5',
            candidate_id='six',task_limit_usd='1',store_path=path)
    assert r['status']=='APPROVAL_TOTAL_EXHAUSTED'


def test_shared_task_limit_and_astra_once(tmp_path):
    kwargs=dict(daily_limit_usd='5',timezone='Asia/Shanghai',approved=True,approval_id='TEST_ONLY',
        approval_total_usd='5',candidate_id='same',task_limit_usd='1',store_path=tmp_path/'test.db')
    r=budget.reserve_api_budget(scan_id='a',worst_case_usd='.6',role='SOL',**kwargs)
    budget.settle_api_budget(r['reservation_id'],actual_cost_usd=None,request_sent=True,store_path=kwargs['store_path'])
    assert budget.reserve_api_budget(scan_id='b',worst_case_usd='.5',role='ASTRA',**kwargs)['status']=='TASK_BUDGET_EXHAUSTED'


def test_expiry_between_rounds_does_not_send_or_release_known_spend(tmp_path):
    config,receipt,event,now,path=fixture(tmp_path)
    current=[now]
    calls=[]
    def transport(req):
        calls.append(req)
        current[0]=datetime(2026,11,1,16,tzinfo=UTC)
        return output(req,tool=True)
    result=ai.ResponsesResearchClient(config=config,receipt=receipt,budget_path=path,
        transport=transport,key_loader=lambda:None,clock=lambda:current[0]).assess(event,test_only=True)
    assert result['error_code']=='AUTHORIZATION_EXPIRED'
    assert len(calls)==1
    assert result['actual_cost_usd']=='0.0012'


def test_refusal_incomplete_wrong_model_tier_unknown_usage(tmp_path):
    for name in ('refusal','incomplete','model','tier','usage'):
        config,receipt,event,now,path=fixture(tmp_path/name)
        def transport(req):
            r=output(req)
            if name=='refusal': r['output']=[dict(type='message',content=[dict(type='refusal',refusal='not logged')])]
            if name=='incomplete': r['status']='incomplete'
            if name=='model': r['model']='UNEXPECTED'
            if name=='tier': r['service_tier']='priority'
            if name=='usage': r['usage']=None
            return r
        result=ai.ResponsesResearchClient(config=config,receipt=receipt,budget_path=path,
            transport=transport,key_loader=lambda:None,clock=lambda:now).assess(event,test_only=True)
        assert result['state']=='FAILED'
        assert 'not logged' not in json.dumps(result)
        assert (result['actual_cost_usd'] is None)==(name in {'model','tier','usage'})


def test_timeout_retains_reservation_and_no_retry(tmp_path):
    import requests
    config,receipt,event,now,path=fixture(tmp_path)
    seen=[]
    def transport(req):
        seen.append(req)
        raise requests.Timeout('TEST_ONLY_secret_text_not_logged')
    client=ai.ResponsesResearchClient(config=config,receipt=receipt,budget_path=path,
        transport=transport,key_loader=lambda:None,clock=lambda:now)
    result=client.assess(event,test_only=True)
    assert result['budget']['status']=='USAGE_UNKNOWN'
    assert 'secret_text' not in json.dumps(result)
    assert not client.assess(event,test_only=True)['paid_call']
    assert len(seen)==1


def test_no_double_reasoning_charge(tmp_path):
    config,*_=fixture(tmp_path)
    u=dict(input_tokens=100,output_tokens=100,output_tokens_details={'reasoning_tokens':90})
    assert ai.usage_cost(u,config['price_schedule']['gpt-6.1-sol'])==Decimal('0.0012')


def test_capability_authority_cannot_launch_paid_production(tmp_path):
    config,receipt,event,now,path=fixture(tmp_path)
    client=ai.ResponsesResearchClient(config=config,receipt=receipt,budget_path=path,
        transport=lambda _: (_ for _ in ()).throw(AssertionError('no call')),
        key_loader=lambda:None,clock=lambda:now)
    assert client.assess(event)['state']=='BUDGET_NOT_APPROVED'
    assert not path.exists()


def test_nested_private_data_never_enters_model_packet(tmp_path):
    _,_,event,_,_=fixture(tmp_path)
    event.update(password='SECRET',account_id='SECRET',approval={'key':'SECRET'},
        runtime_inputs={'input_generation':3,'credentials':'SECRET'},
        reference_contract={'contract_id':'TEST_ONLY','account':'SECRET',
            'snapshot':{'bbo_received_at':'2026-10-31T15:00:00Z','token':'SECRET'}},
        option_cost={'state':'UNKNOWN','fees':None,'private_note':'SECRET'})
    packet=ai.evidence_packet(event)
    assert 'SECRET' not in json.dumps(packet)
    assert packet['runtime_inputs']['input_generation']==3
    assert packet['option_cost']['fees'] is None
    assert packet['reference_contract']['contract_id']=='TEST_ONLY'
