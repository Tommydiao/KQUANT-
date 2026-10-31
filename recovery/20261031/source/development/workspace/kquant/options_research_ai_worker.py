"""Recoverable, read-only AI consumer beside the existing deterministic worker."""
from concurrent.futures import Future,ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from datetime import UTC,datetime,timedelta
import json
from pathlib import Path
import sqlite3
from threading import Event,Thread
from time import monotonic

from . import options_one_minute as common
from .options_llm_credentials import credential_path
from .options_research_ai import ResponsesResearchClient,approved
from .options_research_ai_lane import review_delivery
from .options_research_ai_store import TaskStore


def captured_event(original,revision):
    if (original.get('policy_id') not in {'STRAT-OPENING-MOMENTUM-5M-V1',
            'STRAT-INTRADAY-MOMENTUM-S1-RESEARCH-V1'}
            or original.get('state')!='NUMERIC_PASS' or not revision.get('reference_contract')):
        return None
    event=deepcopy(original)
    event.update(reference_contract=revision['reference_contract'],option_cost=revision.get('option_cost'),
        event_coverage=revision.get('event_coverage') or revision.get('event_decision'),
        input_revision=original.get('runtime_inputs',{}).get('input_generation') or original['evaluation_id'],
        qualification_revision=revision['revision'],
        withdrawn=revision.get('state') in {'WITHDRAWN','EXPIRED'})
    if event['withdrawn']:
        return None
    return event


class ResearchAIWorker:
    def __init__(self,*,research_path,copilot_path,config_path,receipt_path,cursor_path,hub,clock=None,client_factory=None):
        self.research_path,self.copilot_path=Path(research_path),Path(copilot_path)
        self.config_path,self.receipt_path,self.cursor_path=map(Path,(config_path,receipt_path,cursor_path))
        self.hub,self.clock=hub,clock or (lambda:datetime.now(UTC))
        self.client_factory=client_factory or ResponsesResearchClient
        self.stop=Event()
        self.state={'state':'STARTING','qualified_signal_enabled':False,'orders_enabled':False,'last_error':None}
        self.thread=Thread(target=self._run,name='opening-research-ai',daemon=True)
        self.thread.start()

    def read_revisions(self,after):
        with closing(sqlite3.connect(self.research_path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            until=monotonic()+.2
            db.set_progress_handler(lambda:int(monotonic()>until),1000)
            lower=(self.clock()-timedelta(seconds=300)).isoformat()
            upper=self.clock().isoformat()
            return db.execute('''SELECT r.revision_id,
                CASE WHEN julianday(e.evaluated_at) BETWEEN julianday(?) AND julianday(?) THEN r.payload_json END,
                CASE WHEN julianday(e.evaluated_at) BETWEEN julianday(?) AND julianday(?) THEN e.payload_json END FROM revisions r
                JOIN evaluations e ON e.evaluation_id=r.evaluation_id WHERE r.revision_id>?
                ORDER BY r.revision_id LIMIT 32''',(lower,upper,lower,upper,after)).fetchall()

    def current(self,event):
        from .options_opening_trend_store import detail
        value=detail(event['evaluation_id'],self.research_path)
        if not value:
            return None
        revision=value.get('current_eligibility') or {}
        current=captured_event(value,revision)
        if current is None:
            return {**value,'withdrawn':True}
        # Reuse only a price check actually produced by the qualification lane.
        quote=revision.get('underlying_quote') or {}
        try:
            now=self.clock()
            age=(now-common.timestamp(quote['received_at'])).total_seconds()
            price=quote['last']
            direction=1 if current['right']=='CALL' else -1
            valid=0<=age<=3 and common.finite(price) and direction*(price-current['structure_line'])>0 and current['entry_range'][0]<=price<=current['entry_range'][1]
            current['live_price_check']={'state':'PASS' if valid else 'FAIL','checked_at':quote['received_at']}
        except (KeyError,TypeError,ValueError):
            current['live_price_check']=None
        return current

    def save_cursor(self,after):
        self.cursor_path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.cursor_path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'revision_id':after,'source_path':str(self.research_path.resolve())}),encoding='utf-8')
        temporary.replace(self.cursor_path)

    def _run(self):
        pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='opening-model-request')
        active=None
        try:
            config=json.loads(self.config_path.read_text(encoding='utf-8-sig'))
            receipt=json.loads(self.receipt_path.read_text(encoding='utf-8-sig'))
            if not approved(config,receipt,now=self.clock()):
                self.state['state']='BUDGET_NOT_APPROVED'
                return
            tasks=TaskStore(self.copilot_path)
            self.state['recovered']=tasks.recover(now=self.clock())
            after=0
            if self.cursor_path.is_file():
                cursor=json.loads(self.cursor_path.read_text(encoding='utf-8'))
                if cursor.get('source_path')==str(self.research_path.resolve()):
                    after=int(cursor['revision_id'])
            client=self.client_factory(config=config,receipt=receipt,budget_path=self.copilot_path,clock=self.clock)
            credential_version=None
            credential_valid=False
            astra_access=None
            while not self.stop.is_set():
                try:
                    # The durable revision log closes the gap between source commit
                    # and enqueue. Cursor advances only after each idempotent write.
                    rows=self.read_revisions(after)
                    for identity,raw_revision,raw_original in rows:
                        if raw_original is None:
                            self.save_cursor(identity)
                            after=identity
                            continue
                        revision={**json.loads(raw_revision),'revision':identity}
                        original=json.loads(raw_original)
                        if original.get('policy_id') in {'STRAT-OPENING-MOMENTUM-5M-V1','STRAT-INTRADAY-MOMENTUM-S1-RESEARCH-V1'}:
                            event=captured_event(original,revision)
                            if event:
                                tasks.enqueue(event,now=self.clock())
                        self.save_cursor(identity)
                        after=identity
                    self.state['source_revision_watermark']=after
                    path=credential_path()
                    version=(path.stat().st_mtime_ns,path.stat().st_size) if path.is_file() else None
                    if version is not None and version!=credential_version:
                        probe=client.probe('SOL')
                        credential_valid=probe['state']=='ACCESSIBLE'
                        credential_version=version
                        astra_access=None
                        self.state['capability']=probe
                        self.state['access_blocker']=None if credential_valid else probe['state']
                    if active and active[1].done():
                        job,future=active
                        try:
                            result=future.result()
                        except Exception as exc:
                            result={'state':'FAILED','error_code':type(exc).__name__}
                        result=review_delivery(result,job['event'],self.current(job['event']),now=self.clock())
                        tasks.finish(job,result,now=self.clock())
                        self.hub.publish({'type':'options_one_minute_ai','research_strategy':'opening_momentum',
                            'event_id':job['event']['event_id'],'evaluation_id':job['event']['evaluation_id'],
                            'input_revision':job['event']['input_revision'],'state':result['state'],
                            'delivery_state':result['delivery_state'],'qualified_signal':False})
                        self.state['last_result']=dict(state=result['state'],delivery_state=result['delivery_state'],
                            actual_cost_usd=result.get('actual_cost_usd'),event_id=job['event']['event_id'])
                        if result.get('error_code') in {'API_HTTP_401','RETURNED_MODEL_MISMATCH'} or (job['role']=='SOL' and result.get('error_code')=='API_HTTP_403'):
                            credential_valid=False
                            self.state['access_blocker']=result['error_code']
                        active=None
                    if not active and credential_valid:
                        job=tasks.claim(now=self.clock())
                        if job:
                            if job['role']=='ASTRA' and astra_access is None:
                                astra_access=client.probe('ASTRA')
                                self.state['astra_capability']=astra_access
                            if job['role']=='ASTRA' and astra_access['state']!='ACCESSIBLE':
                                future=Future()
                                future.set_result({'state':'MODEL_NOT_ACCESSIBLE',
                                    'error_code':'ASTRA_ACCESS_UNAVAILABLE','paid_call':False,'actual_cost_usd':None})
                                active=job,future
                            else:
                                active=job,pool.submit(client.assess,job['event'],role=job['role'])
                    self.state.update(state='INFLIGHT' if active else ('READY' if credential_valid else 'WAIT_LOCAL_MODEL_ACCESS'),
                        last_cycle_at=self.clock().isoformat(),last_error=None)
                except Exception as exc:
                    self.state.update(state='DEGRADED',last_error=type(exc).__name__)
                self.stop.wait(.25 if active else .5)
        except Exception as exc:
            self.state.update(state='UNAVAILABLE',last_error=type(exc).__name__)
        finally:
            pool.shutdown(wait=False,cancel_futures=True)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)
