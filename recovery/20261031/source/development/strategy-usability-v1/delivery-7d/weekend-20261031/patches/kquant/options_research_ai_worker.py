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
from .options_research_ai import ResponsesResearchClient,approved,version_identity
from .options_research_ai_lane import review_delivery
from .options_research_ai_store import TaskStore


def supported_policy_ids():
    legacy={'STRAT-OPENING-MOMENTUM-5M-V1','STRAT-INTRADAY-MOMENTUM-S1-RESEARCH-V1'}
    try:
        from first_hour import policies
    except ModuleNotFoundError as exc:
        if exc.name!='first_hour':
            raise
        return legacy
    return legacy|{policy['policy_id'] for policy in policies().values()}


def captured_event(original,revision,*,policy_ids=None,versions=None):
    if (original.get('policy_id') not in (supported_policy_ids() if policy_ids is None else policy_ids)
            or original.get('state')!='NUMERIC_PASS' or not revision.get('reference_contract')):
        return None
    # A shared S0 reference is already reviewed through its owning evaluation.
    # Rendering it in the S1 comparison must not enqueue another paid task.
    if original.get('reference_collection_owner')=='S0' and original.get('parent_evaluation_id'):
        return None
    event=deepcopy(original)
    event.update(reference_contract=revision['reference_contract'],option_cost=revision.get('option_cost'),
        event_coverage=revision.get('event_coverage') or revision.get('event_decision'),
        input_revision=original.get('runtime_inputs',{}).get('input_generation') or original['evaluation_id'],
        qualification_revision=revision['revision'],
        withdrawn=revision.get('state') in {'WITHDRAWN','EXPIRED'})
    if event['withdrawn']:
        return None
    if versions is not None:
        event['_ai_versions']=deepcopy(versions)
    return event


class ResearchAIWorker:
    def __init__(self,*,research_path,copilot_path,config_path,receipt_path,cursor_path,hub,clock=None,client_factory=None):
        self.research_path,self.copilot_path=Path(research_path),Path(copilot_path)
        self.config_path,self.receipt_path,self.cursor_path=map(Path,(config_path,receipt_path,cursor_path))
        self.hub,self.clock=hub,clock or (lambda:datetime.now(UTC))
        self.client_factory=client_factory or ResponsesResearchClient
        self.policy_ids=supported_policy_ids()
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
        # A fixed evaluation and its latest revision suffice. Do not route this
        # private check through page enrichment or a default/live copilot path.
        with closing(sqlite3.connect(self.research_path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)) as db:
            until=monotonic()+.2
            db.set_progress_handler(lambda:int(monotonic()>until),1000)
            row=db.execute('SELECT payload_json FROM evaluations WHERE evaluation_id=?',(event['evaluation_id'],)).fetchone()
            if not row:
                return None
            value=json.loads(row[0])
            row=db.execute('SELECT revision_id,payload_json FROM revisions WHERE evaluation_id=? ORDER BY revision_id DESC LIMIT 1',(event['evaluation_id'],)).fetchone()
            revision={**json.loads(row[1]),'revision':row[0]} if row else {}
        current=captured_event(value,revision,policy_ids=self.policy_ids,versions=event.get('_ai_versions'))
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

    def authorization(self):
        config=json.loads(self.config_path.read_text(encoding='utf-8-sig'))
        receipt=json.loads(self.receipt_path.read_text(encoding='utf-8-sig'))
        if (not isinstance(config.get('prompt_version'),str) or not config['prompt_version']
                or not isinstance(config.get('tools_version'),str) or not config['tools_version']):
            raise ValueError('AI_CONFIG_VERSION_REQUIRED')
        return config,receipt,approved(config,receipt,now=self.clock())

    def save_cursor(self,after):
        self.cursor_path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.cursor_path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'revision_id':after,'source_path':str(self.research_path.resolve())}),encoding='utf-8')
        temporary.replace(self.cursor_path)

    def _run(self):
        pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='opening-model-request')
        active=None
        try:
            tasks=client=None
            client_identity=None
            after=0
            if self.cursor_path.is_file():
                cursor=json.loads(self.cursor_path.read_text(encoding='utf-8'))
                if cursor.get('source_path')==str(self.research_path.resolve()):
                    after=int(cursor['revision_id'])
            credential_version=None
            credential_valid=False
            astra_access=None
            while not self.stop.is_set():
                try:
                    try:
                        config,receipt,authorized=self.authorization()
                        versions=version_identity(config)
                    except (OSError,ValueError,TypeError,KeyError):
                        config=receipt=versions=None
                        authorized=False
                    self.state['authorization_valid']=authorized
                    # Finish sent work even after permission expiry, but retain it
                    # as audit-only. No new capability probe or claim is allowed.
                    if active and active[1].done():
                        job,future=active
                        try:
                            result=future.result()
                        except Exception as exc:
                            result={'state':'FAILED','error_code':type(exc).__name__}
                        try:
                            current=self.current(job['event'])
                            result=review_delivery(result,job['event'],current,now=self.clock())
                            if result.get('state')=='COMPLETED' and current and current.get('withdrawn'):
                                result.update(delivery_state='WITHDRAWN',current_opportunity=False,qualified_signal=False)
                        except (OSError,sqlite3.Error,ValueError,KeyError,TypeError):
                            result={**result,'delivery_state':'EVENT_RECHECK_UNAVAILABLE','current_opportunity':False,'qualified_signal':False}
                        if not authorized or job['event'].get('_ai_versions')!=versions:
                            result.update(delivery_state='AUTHORIZATION_EXPIRED_OR_CHANGED',current_opportunity=False,qualified_signal=False)
                        tasks.finish(job,result,now=self.clock())
                        self.state['last_result']=dict(state=result['state'],delivery_state=result['delivery_state'],
                            actual_cost_usd=result.get('actual_cost_usd'),event_id=job['event']['event_id'])
                        if result.get('error_code') in {'API_HTTP_401','RETURNED_MODEL_MISMATCH'} or (job['role']=='SOL' and result.get('error_code')=='API_HTTP_403'):
                            credential_valid=False
                            self.state['access_blocker']=result['error_code']
                        active=None
                        self.hub.publish({'type':'options_one_minute_ai','research_strategy':'opening_momentum',
                            'event_id':job['event']['event_id'],'evaluation_id':job['event']['evaluation_id'],
                            'input_revision':job['event']['input_revision'],'state':result['state'],
                            'delivery_state':result['delivery_state'],'qualified_signal':False})
                    if not authorized:
                        self.state.update(state='INFLIGHT_AUTHORIZATION_EXPIRED' if active else 'BUDGET_NOT_APPROVED',
                            last_cycle_at=self.clock().isoformat())
                        self.stop.wait(.25 if active else .5)
                        continue
                    if tasks is None:
                        tasks=TaskStore(self.copilot_path)
                        self.state['recovered']=tasks.recover(now=self.clock())
                    identity=common.digest([config,receipt])
                    if not active and identity!=client_identity:
                        client=self.client_factory(config=config,receipt=receipt,budget_path=self.copilot_path,clock=self.clock)
                        client_identity=identity
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
                        if original.get('policy_id') in self.policy_ids:
                            event=captured_event(original,revision,policy_ids=self.policy_ids,versions=versions)
                            if event:
                                tasks.enqueue(event,now=self.clock())
                        self.save_cursor(identity)
                        after=identity
                    self.state['source_revision_watermark']=after
                    path=credential_path()
                    version=(path.stat().st_mtime_ns,path.stat().st_size) if path.is_file() else None
                    if version is None:
                        credential_valid=False
                        credential_version=None
                        self.state['access_blocker']='MISSING_LOCAL_KEY'
                    if not active and version is not None and version!=credential_version:
                        credential_version=version
                        try:
                            probe=client.probe('SOL')
                        except Exception as exc:
                            probe={'state':'PROBE_FAILED','error_code':type(exc).__name__,'paid_call':False}
                        credential_valid=probe['state']=='ACCESSIBLE'
                        astra_access=None
                        self.state['capability']=probe
                        self.state['access_blocker']=None if credential_valid else probe['state']
                    if not active and credential_valid:
                        job=tasks.claim(now=self.clock(),versions=versions)
                        if job:
                            try:
                                current=self.current(job['event'])
                            except (OSError,sqlite3.Error,ValueError,KeyError,TypeError):
                                tasks.finish(job,{'state':'UNAVAILABLE','delivery_state':'EVENT_RECHECK_UNAVAILABLE',
                                    'paid_call':False,'qualified_signal':False},now=self.clock())
                                continue
                            if (not current or current.get('withdrawn')
                                    or current.get('input_revision')!=job['event'].get('input_revision')
                                    or current.get('runtime_inputs')!=job['event'].get('runtime_inputs')
                                    or self.clock()>=common.timestamp(job['event']['deadline_at'])):
                                tasks.finish(job,{'state':'STALE','delivery_state':'INPUT_REVISED_OR_EXPIRED',
                                    'paid_call':False,'qualified_signal':False},now=self.clock())
                                continue
                            if job['role']=='ASTRA' and astra_access is None:
                                try:
                                    astra_access=client.probe('ASTRA')
                                except Exception as exc:
                                    astra_access={'state':'PROBE_FAILED','error_code':type(exc).__name__,'paid_call':False}
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
