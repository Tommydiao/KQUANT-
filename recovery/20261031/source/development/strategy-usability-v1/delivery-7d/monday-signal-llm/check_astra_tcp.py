"""TEST_ONLY actual TCP/Gateway positive outbox request; no model or SDK access."""
from contextlib import closing
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
import sqlite3
import sys
from tools.bootstrap import activate

HERE, BASE = activate()
sys.path[:0] = [str(BASE/'tests'), str(BASE/'crypto')]
import requests
from pytest import MonkeyPatch
from test_positive_contract_tcp import tcp_server
from kquant import options_one_minute as common
from kquant import options_opening_trend_store as store
from kquant.config import KquantConfig
from kquant.dashboard.app import create_app
from kquant.options_opening_momentum_journal import initialize
from kquant.options_research_ai import config_identity
from kquant.options_research_ai_store import TaskStore
from kquant.options_signal_copilot import initialize_copilot_store
from kquant.security import generate_password_hash
from kquant_crypto.gateway import create_gateway_app


def main():
    now = datetime.now(UTC)
    out = HERE/'evidence'/('astra-tcp-'+now.strftime('%Y%m%d-%H%M%S'))
    out.mkdir()
    report = dict(test_only=True, sdk_calls=0, model_calls=0, real_api_fees=None,
        production_writes=0, scope='actual TCP API/Gateway authenticated outbox, no model transport',
        market_acceptance=False, tests={})
    with MonkeyPatch.context() as patch:
        for key, value in {
            'LOCALAPPDATA':str(out/'local'), 'KQUANT_REQUIRE_API_AUTH':'true',
            'KQUANT_REALTIME_SUPERVISOR_ENABLED':'false', 'KQUANT_OPTION_RADAR_ENABLED':'false',
            'KQUANT_API_AUTH_TOKEN':'TEST_ONLY-astra-token', 'KQUANT_WORKSPACE_LOGIN_ENABLED':'true',
            'KQUANT_WORKSPACE_LOGIN_EMAIL':'test-only@example.invalid',
            'KQUANT_WORKSPACE_LOGIN_PASSWORD_HASH':generate_password_hash('TEST_ONLY_not_a_user_password'),
            'KQUANT_WORKSPACE_SESSION_SECRET':'TEST_ONLY_SECRET'*4,
        }.items():
            patch.setenv(key,value)
        patch.delenv('KQUANT_OPTION_FOUNDATION_ROOT',raising=False)
        patch.setattr(common,'ROOT',out)
        research=out/'TEST_ONLY-research.sqlite3'
        store.initialize(research)
        initialize(research)
        copilot=out/'work/options_signal_copilot/signal_copilot.sqlite3'
        initialize_copilot_store(copilot)
        TaskStore(copilot)
        config=json.loads((HERE/'config/research_ai.json').read_text(encoding='utf-8'))
        receipt=dict(gate='O-SETUP',status='APPROVED',approved_by='OWNER',
            user_reply_id='TEST_ONLY_NOT_REAL_OWNER',approval_id='TEST_ONLY_TCP',
            config_hash=config_identity(config),approved_at=(now-timedelta(seconds=1)).isoformat(),
            capability_tests_allowed=True,live_paid_research_allowed=True)
        for target,value in (
            (out/'config/options_opening_research_ai.json',config),
            (out/'config/review_acceptances/opening_ai_budget.json',receipt)):
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(value),encoding='utf-8')
        event=dict(event_id='TEST_ONLY_ASTRA_EVENT',evaluation_id='TEST_ONLY_ASTRA_EVAL',
            policy_id='STRAT-INTRADAY-MOMENTUM-S1-RESEARCH-V1',policy_hash='TEST_ONLY_POLICY',
            symbol='TEST_ONLY',right='CALL',session=now.date().isoformat(),
            state='NUMERIC_PASS',evaluated_at=now.isoformat(),
            deadline_at=(now+timedelta(seconds=299)).isoformat(),
            bar_evidence=dict(open=10,high=12,low=9,close=11),
            structure_line=9,entry_range=[11,11.5],runtime_inputs={'input_generation':1},
            research_only=True,qualified_signal=False,test_only=True)
        store.persist([event],research)
        revision=dict(state='PENDING',checked_at=now.isoformat(),
            reference_contract={'contract_id':'TEST_ONLY_CONTRACT','snapshot':{'bbo_received_at':now.isoformat()}},
            underlying_quote={'last':11,'received_at':now.isoformat()},test_only=True)
        with closing(sqlite3.connect(research)) as db, db:
            db.execute('INSERT INTO revisions(evaluation_id,checked_at,state,payload_json) VALUES(?,?,?,?)',
                (event['evaluation_id'],now.isoformat(),'PENDING',json.dumps(revision)))
        app=create_app(config=KquantConfig(db_path=out/'TEST_ONLY-business.sqlite3',outputs_dir=out/'outputs'),
            research_store=research,research_clock=lambda:now,manual_store=out/'TEST_ONLY-manual.sqlite3')
        try:
            with tcp_server(app,lifespan='off') as backend:
                gateway=create_gateway_app(stocks_url=backend,crypto_url=backend,
                    web_dist_dir=HERE/'build/unified',stocks_api_token='TEST_ONLY-astra-token')
                with tcp_server(gateway) as url, requests.Session() as client:
                    login=client.post(url+'/api/auth/login',json={'email':'test-only@example.invalid',
                        'password':'TEST_ONLY_not_a_user_password'},timeout=5)
                    report['tests']['login']=login.status_code
                    assert login.status_code==200,login.text
                    payload=dict(evaluation_id=event['evaluation_id'],role='ASTRA')
                    first=client.post(url+'/api/options/opening-trend/ai-review',json=payload,timeout=5)
                    report['tests']['positive']={'status':first.status_code,'body':first.json()}
                    assert first.status_code==200 and first.json()['state']=='QUEUED',first.text
                    second=client.post(url+'/api/options/opening-trend/ai-review',json=payload,timeout=5)
                    report['tests']['duplicate']={'status':second.status_code,'body':second.json()}
                    assert second.status_code==200 and second.json()['state']=='IDEMPOTENT',second.text
                    invalid=client.post(url+'/api/options/opening-trend/ai-review',json={**payload,'role':'SOL'},timeout=5)
                    report['tests']['invalid_role']=invalid.status_code
                    assert invalid.status_code==422
                    missing=client.post(url+'/api/options/opening-trend/ai-review',json={**payload,'evaluation_id':'TEST_ONLY_MISSING'},timeout=5)
                    report['tests']['missing_reference']=missing.status_code
                    assert missing.status_code==409
                    anonymous=requests.post(url+'/api/options/opening-trend/ai-review',json=payload,timeout=5)
                    report['tests']['anonymous']=anonymous.status_code
                    assert anonymous.status_code==401
            with closing(sqlite3.connect(copilot)) as db:
                rows=db.execute('SELECT role,state,purpose FROM llm_work_queue').fetchall()
                report['queue_rows']=rows
                assert rows==[('ASTRA','QUEUED','OPENING_READ_ONLY_RESEARCH')],rows
                report['reservations']=db.execute('SELECT count(*) FROM llm_budget_reservations').fetchone()[0]
                assert report['reservations']==0
            report['passed']=True
        except Exception as exc:
            report['passed']=False
            report['error_type']=type(exc).__name__
            raise
        finally:
            app.state.research_http_snapshots.close()
            (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print(json.dumps({'out':str(out),'report':report}))


if __name__=='__main__':
    main()
