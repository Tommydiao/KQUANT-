"""Opening AI outbox in the existing copilot role; no order/Paper initialization."""
from contextlib import closing
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from time import monotonic

from . import options_api_budget as budget
from . import options_one_minute as common
from .options_research_ai import MODELS,evidence_packet


class TaskStore:
    def __init__(self,path,*,initialize=True):
        self.path=Path(path)
        if not self.path.is_file():
            raise ValueError('EXISTING_COPILOT_STORE_REQUIRED')
        if initialize:
            budget.initialize_api_budget_store(store_path=self.path)
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
        material=common.digest(evidence_packet(event))
        # BBO refreshes do not purchase the same event analysis again. New native
        # input generations/evaluations or a changed contract are distinct work.
        generation=[event['event_id'],event.get('evaluation_id'),event.get('runtime_inputs'),
            event.get('input_revision'),(event.get('reference_contract') or {}).get('contract_id')]
        return 'opening-ai:'+common.digest([generation,MODELS[role]]),material

    def enqueue(self,event,*,role='SOL',now):
        if role not in MODELS or event.get('state')!='NUMERIC_PASS':
            return 'INELIGIBLE'
        if common.timestamp(event['deadline_at'])<=now:
            return 'EXPIRED'
        identity,material=self.identity(event,role)
        stamp=now.isoformat()
        payload=common.canonical({'captured':event,'result':None,'schema':'OPENING_AI_TASK_V1'})
        with self.connection() as db,db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM llm_work_queue WHERE work_id=?',(identity,)).fetchone():
                return 'IDEMPOTENT'
            db.execute("UPDATE llm_work_queue SET state='REJECTED',deferred_reason='INPUT_REVISED',updated_at=? WHERE candidate_id=? AND role=? AND purpose='OPENING_READ_ONLY_RESEARCH' AND state='QUEUED'",(stamp,event['event_id'],role))
            db.execute('INSERT INTO ai_assessments VALUES (?,?,?,?,?,?,?)',
                (identity,event['event_id'],material,MODELS[role],'RESEARCH_AI_QUEUED',payload,stamp))
            db.execute("INSERT INTO llm_work_queue VALUES (?,?,?,?,?,?,'QUEUED',NULL,?,NULL,NULL,?)",
                (identity,role,event['event_id'],'OPENING_READ_ONLY_RESEARCH','',0,stamp,stamp))
        return 'QUEUED'

    def claim(self,*,now):
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
            if now>=common.timestamp(event['deadline_at']):
                db.execute("UPDATE llm_work_queue SET state='DEFERRED',deferred_reason='EXPIRED',updated_at=? WHERE work_id=?",(stamp,row['work_id']))
                return None
            db.execute("UPDATE llm_work_queue SET state='LEASED',leased_at=?,updated_at=? WHERE work_id=? AND state='QUEUED'",(stamp,stamp,row['work_id']))
            return {'work_id':row['work_id'],'role':row['role'],'event':event}

    def finish(self,job,result,*,now):
        with self.connection() as db,db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE ai_assessments SET state=?,payload_json=?,created_at=? WHERE assessment_id=?',
                ('RESEARCH_AI_'+result.get('state','FAILED'),common.canonical({'schema':'OPENING_AI_TASK_V1',
                    'captured':job['event'],'result':result}),now.isoformat(),job['work_id']))
            db.execute("UPDATE llm_work_queue SET state='COMPLETED',completed_at=?,updated_at=? WHERE work_id=? AND state='LEASED'",(now.isoformat(),now.isoformat(),job['work_id']))

    def recover(self,*,now):
        # A sent/uncertain request is never replayed after a process loss. The budget
        # reservation remains held until reconciled; only never-sent work can retry.
        with self.connection() as db,db:
            db.execute('BEGIN IMMEDIATE')
            rows=db.execute("SELECT q.work_id,a.payload_json,q.role FROM llm_work_queue q JOIN ai_assessments a ON a.assessment_id=q.work_id WHERE q.state='LEASED' AND q.purpose='OPENING_READ_ONLY_RESEARCH' LIMIT 100").fetchall()
            for row in rows:
                event=json.loads(row['payload_json'])['captured']
                scan='opening-ai:'+row['role']+':'+common.digest(evidence_packet(event))
                prior=db.execute('SELECT request_sent FROM llm_budget_reservations WHERE scan_id=?',(scan,)).fetchone()
                state='DEFERRED' if prior and prior[0] else 'QUEUED'
                reason='RECOVERY_USAGE_RECONCILIATION_REQUIRED' if state=='DEFERRED' else 'RECOVERED_BEFORE_REQUEST'
                db.execute('UPDATE llm_work_queue SET state=?,deferred_reason=?,updated_at=? WHERE work_id=?',(state,reason,now.isoformat(),row['work_id']))
            return len(rows)


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
        rows=db.execute('SELECT signal_id,model_id,state,payload_json,created_at FROM ai_assessments WHERE signal_id IN ('+','.join('?' for _ in ids)+') ORDER BY created_at DESC LIMIT 1333',ids).fetchall()
    output={}
    for identity,model,state,raw,created in rows:
        if identity in output:
            continue
        value=json.loads(raw)
        if value.get('schema')!='OPENING_AI_TASK_V1':
            continue
        result=value.get('result') or {}
        output[identity]={'model':model,'state':result.get('state',state),'delivery_state':result.get('delivery_state'),
            'assessment':result.get('assessment'),'actual_cost_usd':result.get('actual_cost_usd'),
            'error_code':result.get('error_code'),'source_refs':result.get('source_refs'),
            'deadline_at':value['captured'].get('deadline_at'),'input_revision':value['captured'].get('input_revision'),
            'evaluation_id':value['captured'].get('evaluation_id'),
            'input_hash':common.digest(evidence_packet(value['captured'])),'created_at':created,'qualified_signal':False}
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
    except (OSError,sqlite3.Error,ValueError,KeyError):
        for row in rows:
            row['ai_review']={'state':'UNAVAILABLE','qualified_signal':False}
