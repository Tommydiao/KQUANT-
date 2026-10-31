"""Real candidate FastAPI/auth/AI outbox; isolated TEST_ONLY files, no paid calls.

Run this weekend test file separately from other folders' bootstrap modules.
Lifespan is intentionally not entered: this is authenticated route acceptance,
not service startup, market acquisition or matched-hour evidence.
"""
from contextlib import closing
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import importlib
import json
from pathlib import Path
import sqlite3
import sys
from urllib.parse import unquote, urlsplit

import pytest
from fastapi.testclient import TestClient

from bootstrap import activate, HERE
activate()
sys.path.insert(0, str(HERE.parent/'opening-first-hour'))


@pytest.fixture
def route_case(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('TEST_ONLY_EXTERNAL_OR_PAID_CALL_FORBIDDEN')
    monkeypatch.setattr('requests.get',forbidden)
    monkeypatch.setattr('requests.post',forbidden)
    # Guard every sqlite connection, including ones made by application imports.
    original_connect=sqlite3.connect
    opened=[]
    def bounded_connect(database,*args,**kwargs):
        text=str(database)
        if text==':memory:':
            return original_connect(database,*args,**kwargs)
        if text.startswith('file:'):
            text=unquote(urlsplit(text).path)
            if len(text)>2 and text[0]=='/' and text[2]==':':
                text=text[1:]
        path=Path(text).resolve()
        assert path.is_relative_to(tmp_path.resolve()), 'TEST_ONLY_DATABASE_SCOPE_VIOLATION'
        opened.append(path)
        return original_connect(database,*args,**kwargs)
    monkeypatch.setattr(sqlite3,'connect',bounded_connect)
    for name in ('KQUANT_RUNTIME_DATA_ROOT','KQUANT_RUNTIME_PATH_BINDING',
            'KQUANT_RUNTIME_PATH_BINDING_SHA256','KQUANT_OPTION_FOUNDATION_ROOT'):
        monkeypatch.delenv(name,raising=False)
    for name in ('KQUANT_REQUIRE_API_AUTH','KQUANT_REALTIME_SUPERVISOR_ENABLED',
            'KQUANT_OPTION_RADAR_ENABLED','KQUANT_OPTION_FORWARD_PAPER_ENABLED',
            'KQUANT_OPTION_FULL_WATCH_ENABLED','KQUANT_OPTION_TWO_HOUR_RESEARCH_ENABLED',
            'KQUANT_OPTION_ONE_MINUTE_SHADOW_ENABLED'):
        monkeypatch.setenv(name,'false')
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'TEST_ONLY-local-config'))
    monkeypatch.setenv('KQUANT_LOGIN_ENABLED','true')
    monkeypatch.setenv('KQUANT_LOGIN_EMAIL','test-only@example.invalid')
    monkeypatch.setenv('KQUANT_SESSION_SECRET','TEST_ONLY_NOT_A_REAL_SECRET_'*3)

    from kquant import options_one_minute as common
    from kquant import options_research_ai as ai
    from kquant import options_research_ai_store as ai_store
    from kquant import options_opening_trend_store as research_store
    from kquant.options_data_paths import resolve_stores
    from kquant.config import KquantConfig
    from kquant.security import generate_password_hash
    from first_hour import policies
    password='TEST_ONLY_not_a_user_password'
    monkeypatch.setenv('KQUANT_LOGIN_PASSWORD_HASH',generate_password_hash(password))
    monkeypatch.setattr(ai.ResponsesResearchClient,'probe',forbidden)
    monkeypatch.setattr(ai.ResponsesResearchClient,'assess',forbidden)

    root=tmp_path/'TEST_ONLY-code-root'
    monkeypatch.setattr(common,'ROOT',root)
    roles=resolve_stores(root)
    research_store.initialize(roles['opening_research'])
    roles['signal_copilot'].parent.mkdir(parents=True,exist_ok=True)
    with closing(sqlite3.connect(roles['signal_copilot'])) as db,db:
        db.execute('CREATE TABLE ai_assessments(assessment_id TEXT PRIMARY KEY,signal_id TEXT,material_state_hash TEXT,model_id TEXT,state TEXT,payload_json TEXT,created_at TEXT,UNIQUE(signal_id,material_state_hash,model_id))')
    ai_store.TaskStore(roles['signal_copilot'])

    now=datetime(2026,10,31,15,tzinfo=UTC)
    policy=policies()
    parent=dict(evaluation_id='TEST_ONLY_S0_EVALUATION',event_id='TEST_ONLY_S0_EVENT',
        state='NUMERIC_PASS',policy_id=policy['S0']['policy_id'],policy_hash=policy['S0']['policy_hash'],
        session='2026-10-30',symbol='TEST_ONLY',right='CALL',evaluated_at=now.isoformat(),
        deadline_at=(now+timedelta(seconds=299)).isoformat(),runtime_inputs={'input_generation':1},
        structure_line=9,entry_range=[11,11.5],bar_evidence={'open':10,'high':12,'low':9,'close':11})
    child={**deepcopy(parent),'evaluation_id':'TEST_ONLY_S1_EVALUATION','event_id':'TEST_ONLY_S1_EVENT',
        'policy_id':policy['S1']['policy_id'],'policy_hash':policy['S1']['policy_hash'],
        'reference_collection_owner':'S0','parent_evaluation_id':parent['evaluation_id'],
        'economic_opportunity_id':'TEST_ONLY_SHARED_ECONOMIC','research_only':True}
    revision=dict(state='PENDING',checked_at=now.isoformat(),reasons=['TEST_ONLY_REFERENCE'],
        reference_contract={'contract_id':'TEST_ONLY_CONTRACT','snapshot':{'bbo_received_at':now.isoformat()}},
        underlying_quote={'last':11,'received_at':now.isoformat()})
    with closing(sqlite3.connect(roles['opening_research'])) as db,db:
        for row in (parent,child):
            db.execute('INSERT INTO evaluations VALUES(?,?,?,?,?,?,?,?)',
                (row['evaluation_id'],row['policy_hash'],row['session'],row['symbol'],row['right'],
                 row['evaluated_at'],row['state'],json.dumps(row)))
        db.execute('INSERT INTO revisions VALUES(1,?,?,?,?)',
            (parent['evaluation_id'],now.isoformat(),revision['state'],json.dumps(revision)))

    config=json.loads((HERE/'config/research_ai.json').read_text(encoding='utf-8'))
    receipt=dict(gate='O-SETUP',status='APPROVED',approved_by='OWNER',
        user_reply_id='TEST_ONLY_NOT_OWNER',approval_id='TEST_ONLY_AUTHENTICATED_ROUTE',
        config_hash=ai.config_identity(config),approved_at='2026-10-31T14:00:00Z',
        authorization_total_usd='5',task_limit_usd='1',valid_until=config['valid_until'],
        capability_tests_allowed=True,live_paid_research_allowed=True)
    config_path=root/'config/options_opening_research_ai.json'
    receipt_path=root/'config/review_acceptances/opening_ai_budget.json'
    receipt_path.parent.mkdir(parents=True,exist_ok=True)
    config_path.write_text(json.dumps(config),encoding='utf-8')
    receipt_path.write_text(json.dumps(receipt),encoding='utf-8')
    dashboard=importlib.import_module('kquant.dashboard.app')
    assert Path(dashboard.__file__).resolve()==(HERE/'patches/kquant/dashboard/app.py').resolve()
    app=dashboard.create_app(config=KquantConfig(db_path=roles['main'],outputs_dir=root/'outputs'),
        research_store=roles['opening_research'],manual_store=roles['minute'],research_clock=lambda:now)
    client=TestClient(app)
    def login():
        response=client.post('/api/auth/login',json={'email':'test-only@example.invalid','password':password})
        assert response.status_code==200,response.text
    def jobs():
        with closing(sqlite3.connect(roles['signal_copilot'])) as db:
            return db.execute('SELECT q.work_id,q.candidate_id,a.payload_json FROM llm_work_queue q '
                'JOIN ai_assessments a ON a.assessment_id=q.work_id ORDER BY q.work_id').fetchall()
    yield dict(client=client,app=app,login=login,jobs=jobs,roles=roles,parent=parent,child=child,
        config=config,receipt=receipt,receipt_path=receipt_path,config_path=config_path,now=now,
        ai=ai,ai_store=ai_store,opened=opened)
    client.close()
    assert app.state.realtime_supervisor._thread is None
    assert app.state.option_radar_supervisor._thread is None
    assert opened and all(path.is_relative_to(tmp_path.resolve()) for path in opened)


def test_authenticated_parent_routing_versions_and_idempotent_repeated_display(route_case):
    h=route_case
    h['login']()
    payload={'role':'ASTRA','evaluation_id':h['child']['evaluation_id']}
    response=h['client'].post('/api/options/opening-trend/ai-review',json=payload)
    assert response.status_code==200,response.text
    assert response.json()['state']=='QUEUED'
    assert response.json()['paid_call'] is False
    rows=h['jobs']()
    assert len(rows)==1
    work_id,candidate_id,raw=rows[0]
    captured=json.loads(raw)['captured']
    assert candidate_id==h['parent']['event_id']
    assert captured['evaluation_id']==h['parent']['evaluation_id']
    assert captured['event_id']!=h['child']['event_id']
    assert captured['_ai_versions']==h['ai'].version_identity(h['config'])
    assert work_id==h['ai'].task_identity(captured,'ASTRA',h['config'])
    assert json.loads(raw)['scan_id']==work_id
    again=h['client'].post('/api/options/opening-trend/ai-review',json=payload)
    parent=h['client'].post('/api/options/opening-trend/ai-review',json={**payload,
        'evaluation_id':h['parent']['evaluation_id']})
    assert again.json()['state']==parent.json()['state']=='IDEMPOTENT'
    assert len(h['jobs']())==1


def test_unauthenticated_and_forged_gateway_header_cannot_enqueue(route_case):
    h=route_case
    response=h['client'].post('/api/options/opening-trend/ai-review',json={
        'role':'ASTRA','evaluation_id':h['child']['evaluation_id']},
        headers={'X-KQUANT-WORKSPACE-USER':'forged@example.invalid'})
    assert response.status_code==401
    assert h['jobs']()==[]


@pytest.mark.parametrize('restriction',['capability_only','expired','revoked'])
def test_authenticated_production_route_refuses_unapproved_scope(route_case,restriction):
    h=route_case
    if restriction=='capability_only':
        h['receipt']['live_paid_research_allowed']=False
    elif restriction=='revoked':
        h['receipt']['status']='REVOKED'
    else:
        h['config']['valid_until']=h['now'].isoformat()
        h['receipt']['config_hash']=h['ai'].config_identity(h['config'])
        h['config_path'].write_text(json.dumps(h['config']),encoding='utf-8')
    h['receipt_path'].write_text(json.dumps(h['receipt']),encoding='utf-8')
    h['login']()
    response=h['client'].post('/api/options/opening-trend/ai-review',json={
        'role':'ASTRA','evaluation_id':h['child']['evaluation_id']})
    assert response.status_code==403,response.text
    assert response.json()['detail']=='AI_BUDGET_NOT_APPROVED'
    assert h['jobs']()==[]


def test_authenticated_missing_reference_owner_does_not_fallback_to_child(route_case):
    h=route_case
    with closing(sqlite3.connect(h['roles']['opening_research'])) as db,db:
        db.execute('DELETE FROM evaluations WHERE evaluation_id=?',(h['parent']['evaluation_id'],))
    h['login']()
    response=h['client'].post('/api/options/opening-trend/ai-review',json={
        'role':'ASTRA','evaluation_id':h['child']['evaluation_id']})
    assert response.status_code==409,response.text
    assert response.json()['detail']=='CURRENT_REFERENCE_RESEARCH_REQUIRED'
    assert h['jobs']()==[]


def test_authenticated_route_does_not_accept_sol_or_automatic_role(route_case):
    h=route_case
    h['login']()
    response=h['client'].post('/api/options/opening-trend/ai-review',json={
        'role':'SOL','evaluation_id':h['parent']['evaluation_id']})
    assert response.status_code==422,response.text
    assert h['jobs']()==[]
