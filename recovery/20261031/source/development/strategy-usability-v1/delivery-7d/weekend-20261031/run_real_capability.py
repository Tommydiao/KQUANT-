"""Bounded official API acceptance. Only the existing copilot budget is writable."""
import argparse
from contextlib import closing
from datetime import UTC,datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from bootstrap import activate,HERE,BASE

activate()
from kquant.options_llm_credentials import credential_path
from kquant.options_research_ai import ResponsesResearchClient,approved

ROOT=BASE.parents[2]


def execute(role,case,execute=False):
    now=datetime.now(UTC)
    config=json.loads((HERE/'config/research_ai.json').read_text())
    receipt=json.loads((HERE/'config/owner_weekend_api.json').read_text())
    evidence=HERE/'evidence'
    evidence.mkdir(exist_ok=True)
    result={'checked_at':now.isoformat(),'scope':'TEST_ONLY_BUSINESS_REAL_API_COST',
        'natural_signal':False,'production_start':False,'role':role,'case':case,
        'paid_call':False,'result':None}
    path=credential_path()
    if not approved(config,receipt,now=now,test_only=True):
        result['state']='AUTHORIZATION_EXPIRED_OR_INVALID'
    elif not path.is_file():
        result['state']='MISSING_LOCAL_DPAPI_NO_NETWORK'
    elif not execute:
        result['state']='READY_FOR_EXPLICIT_CAPABILITY_EXECUTION'
    else:
        # The original five-role map remains authoritative; never create/migrate it.
        roles=json.loads((ROOT/'runtime/config/new-epoch-store-paths.json').read_text(encoding='utf-8-sig'))
        store=Path(roles['stores']['signal_copilot']).resolve(strict=True)
        with closing(sqlite3.connect(store.as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            db.execute('PRAGMA query_only=ON')
            tables={x[0] for x in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            columns={x[1] for x in db.execute('PRAGMA table_info(llm_budget_reservations)')}
        if not {'llm_budget_days','llm_budget_reservations','llm_work_queue'}<=tables or not {
                'approval_id','role','candidate_id','purpose','notification_key'}<=columns:
            result['state']='EXISTING_LEDGER_SCHEMA_NOT_READY_NO_WRITE_NO_API'
        else:
            version=sha256(path.read_bytes()).hexdigest()
            gate=evidence/('key-probe-'+role.lower()+'.json')
            prior=json.loads(gate.read_text()) if gate.is_file() else {}
            client=ResponsesResearchClient(config=config,receipt=receipt,budget_path=store)
            if prior.get('credential_version')==version and prior.get('state')!='ACCESSIBLE':
                result['state']='UNCHANGED_CREDENTIAL_PREVIOUS_PROBE_FAILED_NO_RETRY'
            else:
                probe=prior if prior.get('credential_version')==version else client.probe(role)
                if probe is not prior:
                    probe.update(credential_version=version,checked_at=now.isoformat())
                    gate.write_text(json.dumps(probe,indent=2)+'\n')
                result['probe']={k:v for k,v in probe.items() if k!='credential_version'}
                if probe['state']!='ACCESSIBLE':
                    result['state']='MODEL_ACCESS_NOT_VERIFIED'
                else:
                    event=dict(event_id='TEST_ONLY_WEEKEND_'+role+'_'+case,
                        input_revision=1,session='TEST_ONLY',state='NUMERIC_PASS',
                        bar_evidence=dict(open=10,high=12,low=9,close=11),
                        option_cost={'state':'UNKNOWN','cost':None},deadline_at=config['valid_until'])
                    result['result']=client.assess(event,role=role,test_only=True,
                        capability_simple=case=='minimal')
                    result['state']=result['result']['state']
                    result['paid_call']=result['result']['paid_call']
    target=evidence/('real-'+role.lower()+'-'+case+'-'+now.strftime('%Y%m%dT%H%M%S%fZ')+'.json')
    target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'evidence':str(target),'state':result['state'],'paid_call':result['paid_call']}))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--role',choices=['SOL','ASTRA'],default='SOL')
    parser.add_argument('--case',choices=['minimal','math'],default='math')
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    execute(args.role,args.case,args.execute)
