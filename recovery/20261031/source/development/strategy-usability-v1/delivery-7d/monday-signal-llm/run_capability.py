"""Explicit real paid capability test after exact approval; never production signals."""
import argparse
from datetime import UTC,datetime
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[4]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--receipt',type=Path,required=True)
    parser.add_argument('--projection',type=Path,required=True)
    parser.add_argument('--budget-store',type=Path,required=True)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--role',choices=('SOL','ASTRA'),default='SOL')
    args=parser.parse_args()
    projection_path=args.projection.resolve()
    if not projection_path.is_relative_to((HERE/'release').resolve()):
        raise SystemExit('EXACT_LOCAL_PROJECTION_REQUIRED')
    projection=json.loads(projection_path.read_text(encoding='utf-8'))
    if projection.get('model_cost_boundary')!='QUARANTINE_RETURNED_MODEL_IDENTITY_V1':
        raise SystemExit('PAID_ADAPTER_BOUNDARY_NOT_VERIFIED')
    os.environ['KQUANT_TEST_FROZEN_PROJECTION']=str(projection_path)
    from tools.bootstrap import activate
    activate(verify=True)
    from kquant.options_research_ai import ResponsesResearchClient,approved,config_identity
    config=json.loads((HERE/'config/research_ai.json').read_text(encoding='utf-8'))
    receipt=json.loads(args.receipt.read_text(encoding='utf-8-sig'))
    now=datetime.now(UTC)
    if not approved(config,receipt,now=now,test_only=True):
        raise SystemExit('ACCURATE_BUDGET_ACCEPTANCE_REQUIRED')
    # The five-role map prevents accidental new ledgers or a second daily budget.
    roles=json.loads((ROOT/'runtime/config/new-epoch-store-paths.json').read_text(encoding='utf-8-sig'))['stores']
    possible=[Path(path).resolve() for role,path in roles.items() if 'copilot' in role]
    if args.budget_store.resolve() not in possible or not args.budget_store.is_file():
        raise SystemExit('EXISTING_COPILOT_ROLE_REQUIRED')
    if not args.execute:
        print(json.dumps({'state':'READY_FOR_EXPLICIT_CAPABILITY_EXECUTION','config_hash':config_identity(config),'paid_call':False}))
        return
    entry=json.loads((ROOT/'source/development/workspace/config/local_workspace_entry.json').read_text(encoding='utf-8-sig'))
    if entry['candidate_id']!=projection['candidate_id']:
        raise SystemExit('EXACT_RESEARCH_CANDIDATE_NOT_ACTIVE_NO_API_NO_WRITE')
    # A paid test may record costs, but must not silently migrate the still-live
    # observer's copilot schema before exact launch acceptance activates it.
    with closing(sqlite3.connect(args.budget_store.resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
        db.execute('PRAGMA query_only=ON')
        columns={row[1] for row in db.execute('PRAGMA table_info(llm_budget_reservations)')}
        queue=bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='llm_work_queue'").fetchone())
    if not {'approval_id','role','candidate_id','purpose','notification_key'}<=columns or not queue:
        raise SystemExit('CAPABILITY_LEDGER_EXTENSION_NOT_ACTIVATED_NO_API_NO_WRITE')
    client=ResponsesResearchClient(config=config,receipt=receipt,budget_path=args.budget_store)
    probe=client.probe(args.role)
    result={'checked_at':now.isoformat(),'scope':'TEST_ONLY_BUSINESS_REAL_API_COST','probe':probe,
        'natural_signal':False,'result':None}
    if probe['state']=='ACCESSIBLE':
        result['result']=client.assess(dict(event_id='TEST_ONLY_INITIAL_CAPABILITY_20261018_'+args.role,
            input_revision=1,bar_evidence={'open':10,'high':12,'low':9,'close':11},
            option_cost={'state':'UNKNOWN','round_trip_cost_per_unit':None},
            deadline_at=config['valid_until']),role=args.role,test_only=True)
    target=HERE/'evidence'/('real-'+args.role.lower()+'-capability-'+now.strftime('%Y%m%dT%H%M%SZ')+'.json')
    with target.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,indent=2)
    print(json.dumps({'evidence':str(target),'probe':probe['state'],
        'result':result['result'].get('state') if result['result'] else None}))

if __name__=='__main__':
    main()
