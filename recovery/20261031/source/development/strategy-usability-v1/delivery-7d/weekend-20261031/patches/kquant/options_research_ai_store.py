"""Opening AI outbox in the existing copilot role; no order/Paper initialization."""
from contextlib import closing
from copy import deepcopy
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from time import monotonic

from . import options_one_minute as common
from .options_research_ai_evidence import MODELS,evidence_packet,economic_identity,technical_identity,evidence_catalog


def version_material(event):
    """Pure read-side identity: never import a paid client from page projections."""
    versions=event.get('_ai_versions')
    if versions is None:
        return None
    if (not isinstance(versions,dict) or set(versions)!={'prompt_version','tools_version','config_hash'}
            or any(not isinstance(v,str) or not v for v in versions.values())):
        raise ValueError('AI_VERSION_MATERIAL_INVALID')
    return versions


def reservation_identity(event,role):
    versions=version_material(event)
    if versions is None:
        return 'opening-ai:'+role+':'+common.digest(evidence_packet(event))
    return TaskStore.identity(event,role)[0]


class TaskStore:
    def __init__(self,path,*,initialize=True):
        self.path=Path(path)
        if not self.path.is_file():
            raise ValueError('EXISTING_COPILOT_STORE_REQUIRED')
        if initialize:
            from .options_api_budget import initialize_api_budget_store
            initialize_api_budget_store(store_path=self.path)
        with self.connection() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_assessments'").fetchone():
                raise ValueError('AI_ASSESSMENT_TABLE_MISSING')

    def connection(self,readonly=False):
        db=sqlite3.connect(self.path.resolve().as_uri()+('?mode=ro' if readonly else '?mode=rw'),uri=True,timeout=.2)
        db.row_factory=sqlite3.Row
        until=monotonic()+.3
        db.set_progress_handler(lambda:int(monotonic()>until),1000)
        return closing(db)

    @staticmethod
    def identity(event,role):
        # BBO refreshes do not purchase the same event analysis again. New native
        # input generations/evaluations or a changed contract are distinct work.
        generation=[event['event_id'],event.get('evaluation_id'),event.get('runtime_inputs'),
            event.get('input_revision'),(event.get('reference_contract') or {}).get('contract_id')]
        versions=version_material(event)
        identity='opening-ai:'+common.digest([generation,MODELS[role],versions] if versions is not None
            else [generation,MODELS[role]])
        # The existing assessment UNIQUE key must distinguish prompt/tool versions
        # even when every market fact is unchanged.
        material=common.digest([identity,evidence_packet(event)]) if versions is not None else common.digest(evidence_packet(event))
        return identity,material

    def enqueue(self,event,*,role='SOL',now):
        if role not in MODELS or event.get('state')!='NUMERIC_PASS':
            return 'INELIGIBLE'
        if common.timestamp(event['deadline_at'])<=now:
            return 'EXPIRED'
        event=deepcopy(event)
        candidate_id=economic_identity(event)
        identity,material=self.identity(event,role)
        stamp=now.isoformat()
        payload=common.canonical({'captured':event,'result':None,'schema':'OPENING_AI_TASK_V1',
            'scan_id':reservation_identity(event,role),'versions':version_material(event)})
        with self.connection() as db,db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM llm_work_queue WHERE work_id=?',(identity,)).fetchone():
                return 'IDEMPOTENT'
            if role=='SOL' and event.get('_ai_trigger_mode')=='TECHNICAL_FIRST_AUTO_V1':
                prior=db.execute("""SELECT q.work_id,a.payload_json FROM llm_work_queue q
                    JOIN ai_assessments a ON a.assessment_id=q.work_id
                    WHERE q.candidate_id=? AND q.role='SOL'
                    AND q.purpose='OPENING_READ_ONLY_RESEARCH' LIMIT 1""",(candidate_id,)).fetchone()
                if prior:
                    captured=json.loads(prior['payload_json'])['captured']
                    changed=technical_identity(captured)!=technical_identity(event)
                    if changed:
                        db.execute("UPDATE llm_work_queue SET state='REJECTED',deferred_reason='INPUT_REVISED_MANUAL_REVIEW_REQUIRED',updated_at=? WHERE candidate_id=? AND role='SOL' AND purpose='OPENING_READ_ONLY_RESEARCH' AND state='QUEUED'",(stamp,candidate_id))
                    return 'MANUAL_REVIEW_REQUIRED' if changed else 'ECONOMIC_EVENT_ALREADY_REVIEWED'
            if role=='ASTRA':
                # The queue and budget share this existing database. One immediate
                # transaction prevents two generations from both claiming upgrade.
                if db.execute("SELECT 1 FROM llm_work_queue WHERE candidate_id=? AND role='ASTRA' AND purpose='OPENING_READ_ONLY_RESEARCH' LIMIT 1",(candidate_id,)).fetchone():
                    return 'ASTRA_EVENT_LIMIT'
                if db.execute("SELECT 1 FROM llm_budget_reservations WHERE candidate_id=? AND role='ASTRA' AND state!='RELEASED_NO_REQUEST' LIMIT 1",(candidate_id,)).fetchone():
                    return 'ASTRA_EVENT_LIMIT'
            db.execute("UPDATE llm_work_queue SET state='REJECTED',deferred_reason='INPUT_REVISED',updated_at=? WHERE candidate_id=? AND role=? AND purpose='OPENING_READ_ONLY_RESEARCH' AND state='QUEUED'",(stamp,candidate_id,role))
            db.execute('INSERT INTO ai_assessments VALUES (?,?,?,?,?,?,?)',
                (identity,event['event_id'],material,MODELS[role],'RESEARCH_AI_QUEUED',payload,stamp))
            db.execute("INSERT INTO llm_work_queue VALUES (?,?,?,?,?,?,'QUEUED',NULL,?,NULL,NULL,?)",
                (identity,role,candidate_id,'OPENING_READ_ONLY_RESEARCH','',0,stamp,stamp))
        return 'QUEUED'

    def claim(self,*,now,versions=None):
        stamp=now.isoformat()
        with self.connection() as db,db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM llm_work_queue WHERE state='LEASED' LIMIT 1").fetchone():
                return None
            row=db.execute("""SELECT q.*,a.payload_json FROM llm_work_queue q JOIN ai_assessments a
                ON a.assessment_id=q.work_id WHERE q.purpose='OPENING_READ_ONLY_RESEARCH'
                AND q.state='QUEUED' ORDER BY q.priority DESC,q.enqueued_at,q.work_id LIMIT 1""").fetchone()
            if not row:
                return None
            event=json.loads(row['payload_json'])['captured']
            if versions is not None and version_material(event)!=versions:
                db.execute("UPDATE llm_work_queue SET state='DEFERRED',deferred_reason='AI_CONFIGURATION_CHANGED',updated_at=? WHERE work_id=?",(stamp,row['work_id']))
                return None
            if now>=common.timestamp(event['deadline_at']):
                db.execute("UPDATE llm_work_queue SET state='DEFERRED',deferred_reason='EXPIRED',updated_at=? WHERE work_id=?",(stamp,row['work_id']))
                return None
            db.execute("UPDATE llm_work_queue SET state='LEASED',leased_at=?,updated_at=? WHERE work_id=? AND state='QUEUED'",(stamp,stamp,row['work_id']))
            return {'work_id':row['work_id'],'role':row['role'],'event':event,
                'scan_id':json.loads(row['payload_json']).get('scan_id',reservation_identity(event,row['role']))}

    def finish(self,job,result,*,now):
        with self.connection() as db,db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute("SELECT 1 FROM llm_work_queue WHERE work_id=? AND state='LEASED'",(job['work_id'],)).fetchone():
                return False
            db.execute('UPDATE ai_assessments SET state=?,payload_json=?,created_at=? WHERE assessment_id=?',
                ('RESEARCH_AI_'+result.get('state','FAILED'),common.canonical({'schema':'OPENING_AI_TASK_V1',
                    'captured':job['event'],'result':result,'scan_id':job.get('scan_id',reservation_identity(job['event'],job['role'])),
                    'versions':version_material(job['event'])}),now.isoformat(),job['work_id']))
            db.execute("UPDATE llm_work_queue SET state='COMPLETED',completed_at=?,updated_at=? WHERE work_id=? AND state='LEASED'",(now.isoformat(),now.isoformat(),job['work_id']))
        return True

    def recover(self,*,now):
        # A sent/uncertain request is never replayed after a process loss. The budget
        # reservation remains held until reconciled; only never-sent work can retry.
        with self.connection() as db,db:
            db.execute('BEGIN IMMEDIATE')
            rows=db.execute("SELECT q.work_id,a.payload_json,q.role FROM llm_work_queue q JOIN ai_assessments a ON a.assessment_id=q.work_id WHERE q.state='LEASED' AND q.purpose='OPENING_READ_ONLY_RESEARCH' LIMIT 100").fetchall()
            for row in rows:
                payload=json.loads(row['payload_json'])
                event=payload['captured']
                scan=payload.get('scan_id',reservation_identity(event,row['role']))
                prior=db.execute('SELECT request_sent FROM llm_budget_reservations WHERE scan_id=?',(scan,)).fetchone()
                state='DEFERRED' if prior else 'QUEUED'
                reason=('RECOVERY_USAGE_RECONCILIATION_REQUIRED' if prior[0] else 'RECOVERY_RESERVATION_RECONCILIATION_REQUIRED') if prior else 'RECOVERED_BEFORE_REQUEST'
                db.execute('UPDATE llm_work_queue SET state=?,deferred_reason=?,updated_at=? WHERE work_id=?',(state,reason,now.isoformat(),row['work_id']))
            return len(rows)


def response_metadata(result):
    """Only provider identifiers and token counts; never return response items."""
    output=[]
    for response in (result.get('responses') or [])[:3]:
        if not isinstance(response,dict):
            continue
        value={k:response[k] for k in ('response_id','request_id','model','status','service_tier')
            if isinstance(response.get(k),str)}
        usage=response.get('usage') or {}
        if isinstance(usage,dict):
            safe={k:usage[k] for k in ('input_tokens','output_tokens','total_tokens')
                if type(usage.get(k)) is int and usage[k]>=0}
            for name,keys in (('input_tokens_details',('cached_tokens','cache_write_tokens')),
                              ('output_tokens_details',('reasoning_tokens',))):
                detail=usage.get(name)
                if isinstance(detail,dict):
                    safe[name]={k:detail[k] for k in keys if type(detail.get(k)) is int and detail[k]>=0}
            value['usage']=safe
        output.append(value)
    return output


def summaries(path,events):
    """One bounded read for the existing page snapshot; no model work in GET."""
    ids=sorted(set(x['event_id'] for x in events if x.get('event_id')))
    if not ids or not Path(path).is_file():
        return {}
    if len(ids)>444:
        raise ValueError('AI_SUMMARY_READ_BOUND')
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
        until=monotonic()+.2
        db.set_progress_handler(lambda:int(monotonic()>until),1000)
        rows=db.execute('SELECT a.signal_id,a.model_id,a.state,a.payload_json,a.created_at,q.state,q.deferred_reason '
            'FROM ai_assessments a LEFT JOIN llm_work_queue q ON q.work_id=a.assessment_id WHERE a.signal_id IN ('
            +','.join('?' for _ in ids)+') ORDER BY a.created_at DESC,a.rowid DESC LIMIT 1333',ids).fetchall()
    output={}
    by_model={}
    for identity,model,state,raw,created,queue_state,deferred_reason in rows:
        if (identity,model) in by_model:
            continue
        value=json.loads(raw)
        if value.get('schema')!='OPENING_AI_TASK_V1':
            continue
        result=value.get('result') or {}
        review_state=('COMPLETE' if result.get('state')=='COMPLETED' else 'UNAVAILABLE') if result else 'AI_PENDING'
        if queue_state in {'DEFERRED','REJECTED'} or (result.get('state')=='COMPLETED'
                and result.get('delivery_state') not in {'CURRENT_RESEARCH_REVIEW','CURRENT_TECHNICAL_REVIEW'}):
            review_state='STALE'
        by_model[identity,model]={'model':model,'state':result.get('state',state),'review_state':review_state,
            'queue_state':queue_state,'deferred_reason':deferred_reason,'delivery_state':result.get('delivery_state'),
            'assessment':result.get('assessment'),'actual_cost_usd':result.get('actual_cost_usd'),
            'evidence_catalog':(result.get('replay_evidence_catalog', []) if result.get('replay_provenance')
                else evidence_catalog(value['captured'])),
            'replay_provenance':result.get('replay_provenance'),
            'review_scope':result.get('review_scope'),
            'market_recheck_state':result.get('market_recheck_state'),
            'error_code':result.get('error_code'),'source_refs':result.get('source_refs'),
            'deadline_at':value['captured'].get('deadline_at'),'input_revision':value['captured'].get('input_revision'),
            'evaluation_id':value['captured'].get('evaluation_id'),
            'technical_identity':technical_identity(value['captured']),
            'versions':value.get('versions',version_material(value['captured'])),
            'requested_model':result.get('requested_model'),'returned_model':result.get('actual_model'),
            'actual_model':result.get('actual_model'),'elapsed_seconds':result.get('elapsed_seconds'),
            'responses':response_metadata(result),'endpoint':result.get('endpoint'),
            'reviewed_at':result.get('reviewed_at'),'valid_until':result.get('valid_until',value['captured'].get('deadline_at')),
            'input_hash':common.digest(evidence_packet(value['captured'])),'created_at':created,'qualified_signal':False}
    for (identity,model),value in by_model.items():
        if identity not in output or model==MODELS['SOL']:
            output[identity]=value
    for identity,value in output.items():
        astra=by_model.get((identity,MODELS['ASTRA']))
        if astra is not None and astra is not value:
            value['astra_review']=astra
    return output


def attach(rows,*,path=None):
    """Optional AI display failure cannot remove deterministic research results."""
    from .options_data_paths import resolve_stores
    try:
        path=path or resolve_stores(common.ROOT)['signal_copilot']
        events=[item for row in rows for item in (row,(row.get('strategy_comparison') or {}).get('s1',{})) if item.get('event_id')]
        values=summaries(path,events)
        for event in events:
            summary=values.get(event['event_id'])
            if summary:
                event['ai_review']={**summary,'display_state':'SAME_EVALUATION' if summary.get('evaluation_id')==event.get('evaluation_id') else 'PRIOR_EVALUATION'}
                current={**event,'input_revision':event.get('runtime_inputs',{}).get('input_generation') or event.get('evaluation_id')}
                if summary.get('technical_identity')!=technical_identity(current):
                    event['ai_review'].update(review_state='STALE',display_state='INPUT_REVISED')
    except (OSError,sqlite3.Error,ValueError,KeyError):
        for row in rows:
            row['ai_review']={'state':'UNAVAILABLE','qualified_signal':False}
