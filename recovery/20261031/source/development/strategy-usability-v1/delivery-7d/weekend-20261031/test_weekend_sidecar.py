"""Actual SQLite/thread sidecar with explicit TEST_ONLY clients; never network/live DB."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sqlite3
import sys
from threading import Event
from time import monotonic, sleep

import pytest
from bootstrap import activate, HERE
activate()
sys.path.insert(0, str(HERE.parent / 'opening-first-hour'))

from kquant import options_api_budget as budget
from kquant import options_research_ai as ai
from kquant import options_research_ai_store as store
from kquant import options_research_ai_worker as worker_module
from first_hour import policies, OFFSETS


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('TEST_ONLY_NETWORK_FORBIDDEN')
    monkeypatch.setattr('requests.get', denied)
    monkeypatch.setattr('requests.post', denied)


def wait_for(predicate, timeout=4):
    until=monotonic()+timeout
    while monotonic()<until:
        if predicate():
            return
        sleep(.01)
    assert predicate(), 'TEST_ONLY_WAIT_BOUND'


def config_value():
    return json.loads((HERE/'config/research_ai.json').read_text(encoding='utf-8'))


def event_value(now, index=0, variant='S1'):
    return dict(event_id='TEST_ONLY_EVENT_'+str(index), evaluation_id='TEST_ONLY_EVAL_'+str(index),
        symbol='TEST_ONLY', right='CALL', session='2026-10-30', research_strategy='opening_momentum',
        policy_id=policies()[variant]['policy_id'], state='NUMERIC_PASS',
        deadline_at=(now+timedelta(seconds=299)).isoformat(),
        runtime_inputs={'input_generation':1, 'input_fingerprint':'TEST_ONLY_NATIVE_INPUT'},
        bar_evidence=dict(open=10,high=12,low=9,close=11), structure_line=9,entry_range=[11,11.5])


def revision_value(now):
    return dict(state='PENDING', checked_at=now.isoformat(), revision=1,
        reference_contract={'contract_id':'TEST_ONLY_CONTRACT', 'bid':1, 'ask':1.1,
            'snapshot':{'bbo_received_at':now.isoformat()}},
        underlying_quote={'last':11,'received_at':now.isoformat()})


def make_copilot(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE ai_assessments(assessment_id TEXT PRIMARY KEY,signal_id TEXT,material_state_hash TEXT,model_id TEXT,state TEXT,payload_json TEXT,created_at TEXT,UNIQUE(signal_id,material_state_hash,model_id))')
    return store.TaskStore(path)


class Harness:
    def __init__(self, root, monkeypatch, count=1):
        self.now=datetime(2026,10,31,15,tzinfo=UTC)
        self.root=root
        self.config=config_value()
        self.receipt=dict(gate='O-SETUP', status='APPROVED', approved_by='OWNER',
            user_reply_id='TEST_ONLY_NOT_OWNER', approval_id='TEST_ONLY_SIDECAR',
            config_hash=ai.config_identity(self.config),approved_at='2026-10-31T14:00:00Z',
            authorization_total_usd='5',task_limit_usd='1',valid_until=self.config['valid_until'],
            capability_tests_allowed=True,live_paid_research_allowed=True)
        self.config_path=root/'TEST_ONLY_config.json'
        self.receipt_path=root/'TEST_ONLY_receipt.json'
        self.save_config()
        self.research=root/'TEST_ONLY_research.sqlite3'
        self.copilot=root/'TEST_ONLY_copilot.sqlite3'
        self.tasks=make_copilot(self.copilot)
        self.events=[event_value(self.now,i) for i in range(count)]
        with closing(sqlite3.connect(self.research)) as db, db:
            db.executescript('CREATE TABLE evaluations(evaluation_id TEXT PRIMARY KEY,evaluated_at TEXT,payload_json TEXT); CREATE TABLE revisions(revision_id INTEGER PRIMARY KEY,evaluation_id TEXT,payload_json TEXT);')
            for i,event in enumerate(self.events):
                db.execute('INSERT INTO evaluations VALUES(?,?,?)',(event['evaluation_id'],self.now.isoformat(),json.dumps(event)))
                db.execute('INSERT INTO revisions VALUES(?,?,?)',(i+1,event['evaluation_id'],json.dumps(revision_value(self.now))))
        self.key=root/'TEST_ONLY_key_marker'
        self.key.write_text('TEST_ONLY_NOT_A_CREDENTIAL',encoding='utf-8')
        monkeypatch.setattr(worker_module,'credential_path',lambda:self.key)
        self.calls=[]
        self.probes=[]
        self.published=[]
        self.started=Event()
        self.release=Event()
        self.release.set()
        self.outcome={'state':'COMPLETED','assessment':{'support_refs':['bar_evidence'],
            'opposing_refs':[],'missing_inputs':['cost'],'review_reasons':['READ_ONLY_RESEARCH']},
            'actual_cost_usd':None,'test_only':True,'paid_call':False}
        harness=self
        class Client:
            def __init__(self, **kwargs):
                self.kwargs=kwargs
            def probe(self,role):
                harness.probes.append(role)
                return {'state':'ACCESSIBLE','test_only':True,'paid_call':False}
            def assess(self,event,*,role):
                harness.calls.append((deepcopy(event),role))
                harness.started.set()
                assert harness.release.wait(4), 'TEST_ONLY_MODEL_BARRIER_BOUND'
                return deepcopy(harness.outcome)
        class Hub:
            def publish(self,event):
                harness.published.append(event)
        self.arguments=dict(research_path=self.research,copilot_path=self.copilot,
            config_path=self.config_path,receipt_path=self.receipt_path,
            cursor_path=root/'TEST_ONLY_cursor.json',hub=Hub(),clock=lambda:self.now,client_factory=Client)
        self.worker=None

    def save_config(self):
        self.config_path.write_text(json.dumps(self.config),encoding='utf-8')
        self.receipt_path.write_text(json.dumps(self.receipt),encoding='utf-8')

    def start(self):
        self.worker=worker_module.ResearchAIWorker(**self.arguments)
        return self.worker

    def close(self):
        self.release.set()
        if self.worker:
            self.worker.close()

    def captured(self,index=0):
        return worker_module.captured_event(self.events[index],revision_value(self.now),
            versions=ai.version_identity(self.config))


def test_versioned_identity_exactly_matches_client_and_retains_legacy(tmp_path):
    now=datetime(2026,10,31,15,tzinfo=UTC)
    config=config_value()
    event=worker_module.captured_event(event_value(now),revision_value(now),versions=ai.version_identity(config))
    tasks=make_copilot(tmp_path/'TEST_ONLY.sqlite3')
    assert tasks.identity(event,'SOL')[0]==ai.task_identity(event,'SOL',config)
    assert store.reservation_identity(event,'SOL')==ai.task_identity(event,'SOL',config)
    assert tasks.enqueue(event,now=now)=='QUEUED'
    refresh=deepcopy(event)
    refresh['reference_contract']['bid']=1.01
    refresh['reference_contract']['snapshot']['bbo_received_at']=(now+timedelta(seconds=1)).isoformat()
    assert tasks.enqueue(refresh,now=now)=='IDEMPOTENT'
    config['prompt_version']+='-TEST_ONLY_NEXT'
    refresh['_ai_versions']=ai.version_identity(config)
    assert tasks.enqueue(refresh,now=now)=='QUEUED'
    config['tools_version']+='-TEST_ONLY_NEXT'
    refresh['_ai_versions']=ai.version_identity(config)
    assert tasks.enqueue(refresh,now=now)=='QUEUED'
    legacy={k:v for k,v in event.items() if k!='_ai_versions'}
    assert store.reservation_identity(legacy,'SOL').startswith('opening-ai:SOL:')


@pytest.mark.parametrize('sent',[False,True])
def test_recovery_matches_actual_reservation_and_never_replays_paid_or_reserved(tmp_path,sent):
    now=datetime(2026,10,31,15,tzinfo=UTC)
    config=config_value()
    event=worker_module.captured_event(event_value(now),revision_value(now),versions=ai.version_identity(config))
    path=tmp_path/'TEST_ONLY.sqlite3'
    tasks=make_copilot(path)
    tasks.enqueue(event,now=now)
    job=tasks.claim(now=now,versions=ai.version_identity(config))
    reservation=budget.reserve_api_budget(scan_id=ai.task_identity(event,'SOL',config),
        worst_case_usd='.1',daily_limit_usd='5',timezone='Asia/Shanghai',approved=True,
        role='SOL',candidate_id=event['event_id'],store_path=path)
    if sent:
        budget.mark_api_request_sent(reservation['reservation_id'],store_path=path)
    assert store.TaskStore(path).recover(now=now)==1
    assert tasks.claim(now=now) is None
    with closing(sqlite3.connect(path)) as db:
        state,reason=db.execute('SELECT state,deferred_reason FROM llm_work_queue WHERE work_id=?',(job['work_id'],)).fetchone()
    assert state=='DEFERRED'
    assert reason==('RECOVERY_USAGE_RECONCILIATION_REQUIRED' if sent else 'RECOVERY_RESERVATION_RECONCILIATION_REQUIRED')


def test_unsent_without_reservation_recovers_and_versions_are_checked(tmp_path):
    now=datetime(2026,10,31,15,tzinfo=UTC)
    config=config_value()
    event=worker_module.captured_event(event_value(now),revision_value(now),versions=ai.version_identity(config))
    tasks=make_copilot(tmp_path/'TEST_ONLY.sqlite3')
    tasks.enqueue(event,now=now)
    job=tasks.claim(now=now)
    assert tasks.recover(now=now)==1
    assert not tasks.finish(job,{'state':'COMPLETED'},now=now)
    assert tasks.claim(now=now,versions={**ai.version_identity(config),'prompt_version':'CHANGED'}) is None
    with tasks.connection(readonly=True) as db:
        assert db.execute('SELECT deferred_reason FROM llm_work_queue').fetchone()[0]=='AI_CONFIGURATION_CHANGED'


def test_astra_event_limit_is_atomic_across_generations(tmp_path):
    now=datetime(2026,10,31,15,tzinfo=UTC)
    event=worker_module.captured_event(event_value(now),revision_value(now),versions=ai.version_identity(config_value()))
    tasks=make_copilot(tmp_path/'TEST_ONLY.sqlite3')
    changed={**event,'input_revision':2,'evaluation_id':'TEST_ONLY_NEW_GENERATION'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(tasks.enqueue,item,role='ASTRA',now=now) for item in (event,changed)]
        assert sorted(f.result() for f in futures)==['ASTRA_EVENT_LIMIT','QUEUED']
    assert tasks.enqueue({**changed,'input_revision':3},role='ASTRA',now=now)=='ASTRA_EVENT_LIMIT'


def test_existing_astra_budget_blocks_new_outbox_generation(tmp_path):
    now=datetime(2026,10,31,15,tzinfo=UTC)
    event=worker_module.captured_event(event_value(now),revision_value(now),versions=ai.version_identity(config_value()))
    path=tmp_path/'TEST_ONLY.sqlite3'
    tasks=make_copilot(path)
    budget.reserve_api_budget(scan_id='TEST_ONLY_OLD_ASTRA',worst_case_usd='.1',daily_limit_usd='5',
        timezone='Asia/Shanghai',approved=True,role='ASTRA',candidate_id=event['event_id'],store_path=path)
    assert tasks.enqueue(event,role='ASTRA',now=now)=='ASTRA_EVENT_LIMIT'


def test_actual_first_hour_policy_ids_and_all_eleven_checkpoint_envelopes():
    now=datetime(2026,10,31,15,tzinfo=UTC)
    for variant in ('S0','S1'):
        for minute in OFFSETS:
            original=event_value(now,minute,variant)
            original['calculation_bar_end']=(datetime(2026,10,30,13,30,tzinfo=UTC)+timedelta(minutes=minute)).isoformat()
            assert worker_module.captured_event(original,revision_value(now)) is not None
    assert len(OFFSETS)==11
    shared=event_value(now)
    shared.update(parent_evaluation_id='TEST_ONLY_PARENT',reference_collection_owner='S0')
    assert worker_module.captured_event(shared,revision_value(now)) is None


def test_actual_worker_constructs_captures_versions_and_restores_without_duplicate(tmp_path,monkeypatch):
    h=Harness(tmp_path,monkeypatch)
    try:
        worker=h.start()
        wait_for(lambda:len(h.published)==1)
        assert h.calls[0][0]['_ai_versions']==ai.version_identity(h.config)
        assert h.published[0]['delivery_state']=='CURRENT_TECHNICAL_REVIEW'
        assert not h.published[0]['qualified_signal']
        assert worker.thread.is_alive()
        result=store.summaries(h.copilot,h.events)[h.events[0]['event_id']]
        assert result['versions']==ai.version_identity(h.config)
        worker.close()
        h.start()
        wait_for(lambda:h.worker.state.get('source_revision_watermark')==1)
        assert len(h.calls)==1
    finally:
        h.close()


@pytest.mark.parametrize('fault',['revision','expiry','model_error','quote_age','permission_expiry','receipt_revoked'])
def test_actual_worker_nonblocking_rechecks_revision_expiry_model_and_authority(tmp_path,monkeypatch,fault):
    h=Harness(tmp_path,monkeypatch)
    h.release.clear()
    try:
        worker=h.start()
        assert h.started.wait(3),worker.state
        assert len(worker.read_revisions(0))==1
        assert worker.thread.is_alive()
        if fault=='revision':
            rev={**revision_value(h.now),'state':'WITHDRAWN','reasons':['TEST_ONLY_INPUT_REVISION']}
            with closing(sqlite3.connect(h.research)) as db,db:
                db.execute('INSERT INTO revisions VALUES(2,?,?)',(h.events[0]['evaluation_id'],json.dumps(rev)))
        elif fault=='expiry':
            h.now+=timedelta(seconds=300)
        elif fault=='quote_age':
            h.now+=timedelta(seconds=4)
        elif fault=='model_error':
            h.outcome={'state':'FAILED','error_code':'TEST_ONLY_TIMEOUT','paid_call':False}
        elif fault=='permission_expiry':
            h.now=datetime.fromisoformat(h.config['valid_until'].replace('Z','+00:00'))
        else:
            h.receipt['status']='REVOKED'
            h.save_config()
        h.release.set()
        wait_for(lambda:len(h.published)==1)
        expected={'revision':'WITHDRAWN','expiry':'EXPIRED','quote_age':'CURRENT_TECHNICAL_REVIEW',
            'model_error':'MODEL_UNAVAILABLE','permission_expiry':'AUTHORIZATION_EXPIRED_OR_CHANGED',
            'receipt_revoked':'AUTHORIZATION_EXPIRED_OR_CHANGED'}[fault]
        assert h.published[0]['delivery_state']==expected,worker.state
        if fault=='quote_age':
            with closing(sqlite3.connect(h.copilot)) as db:
                result=json.loads(db.execute('SELECT payload_json FROM ai_assessments').fetchone()[0])['result']
            assert result['market_recheck_state']=='QUOTE_STALE'
            assert result['current_opportunity'] is False
        assert len(h.calls)==1
        with closing(sqlite3.connect(h.research)) as db:
            original=json.loads(db.execute('SELECT payload_json FROM evaluations').fetchone()[0])
        assert original['state']=='NUMERIC_PASS'
        assert worker.thread.is_alive()
    finally:
        h.close()


def test_expired_authority_or_test_only_receipt_never_probes_or_claims(tmp_path,monkeypatch):
    h=Harness(tmp_path,monkeypatch)
    h.receipt['live_paid_research_allowed']=False
    h.save_config()
    try:
        worker=h.start()
        wait_for(lambda:worker.state['state']=='BUDGET_NOT_APPROVED')
        assert h.calls==[] and h.probes==[]
        assert not (tmp_path/'TEST_ONLY_cursor.json').exists()
    finally:
        h.close()


def test_model_access_error_blocks_repeated_probe_and_does_not_stop_worker(tmp_path,monkeypatch):
    h=Harness(tmp_path,monkeypatch,count=2)
    h.outcome={'state':'FAILED','error_code':'API_HTTP_401','paid_call':False}
    try:
        worker=h.start()
        wait_for(lambda:worker.state.get('access_blocker')=='API_HTTP_401')
        sleep(.6)
        assert len(h.calls)==1 and h.probes==['SOL']
        assert worker.thread.is_alive()
        with h.tasks.connection(readonly=True) as db:
            assert db.execute("SELECT COUNT(*) FROM llm_work_queue WHERE state='QUEUED'").fetchone()[0]==1
    finally:
        h.close()


def test_missing_key_blocks_without_network_or_default_store(tmp_path,monkeypatch):
    h=Harness(tmp_path,monkeypatch)
    h.key.unlink()
    try:
        worker=h.start()
        wait_for(lambda:worker.state.get('access_blocker')=='MISSING_LOCAL_KEY')
        assert h.calls==[] and h.probes==[]
        assert worker.thread.is_alive()
    finally:
        h.close()


def test_summary_keeps_sol_success_when_astra_fails_and_exposes_only_safe_metadata(tmp_path):
    now=datetime(2026,10,31,15,tzinfo=UTC)
    config=config_value()
    event=worker_module.captured_event(event_value(now),revision_value(now),versions=ai.version_identity(config))
    path=tmp_path/'TEST_ONLY.sqlite3'
    tasks=make_copilot(path)
    tasks.enqueue(event,now=now)
    job=tasks.claim(now=now)
    tasks.finish(job,dict(state='COMPLETED',delivery_state='CURRENT_RESEARCH_REVIEW',
        requested_model='gpt-6.1-sol',actual_model='gpt-6.1-sol',elapsed_seconds=.4,
        endpoint='https://api.openai.com/v1/responses',
        responses=[dict(response_id='resp_TEST_ONLY',request_id='req_TEST_ONLY',model='gpt-6.1-sol',
            output=[{'type':'reasoning','text':'TEST_ONLY_DO_NOT_EXPOSE'}],
            usage=dict(input_tokens=3,output_tokens=4,output_tokens_details={'reasoning_tokens':2,'text':'DO_NOT_EXPOSE'}))]),now=now)
    tasks.enqueue(event,role='ASTRA',now=now+timedelta(seconds=1))
    job=tasks.claim(now=now+timedelta(seconds=1))
    tasks.finish(job,dict(state='MODEL_NOT_ACCESSIBLE',delivery_state='MODEL_UNAVAILABLE',paid_call=False),now=now+timedelta(seconds=1))
    result=store.summaries(path,[event])[event['event_id']]
    assert result['state']=='COMPLETED'
    assert result['review_state']=='COMPLETE'
    assert result['actual_model']=='gpt-6.1-sol'
    assert result['elapsed_seconds']==.4
    assert result['responses'][0]['usage']['output_tokens_details']=={'reasoning_tokens':2}
    assert 'DO_NOT_EXPOSE' not in json.dumps(result)
    assert result['astra_review']['state']=='MODEL_NOT_ACCESSIBLE'


def test_expired_queued_work_summary_is_stale_not_pending(tmp_path):
    now=datetime(2026,10,31,15,tzinfo=UTC)
    event=worker_module.captured_event(event_value(now),revision_value(now),versions=ai.version_identity(config_value()))
    path=tmp_path/'TEST_ONLY.sqlite3'
    tasks=make_copilot(path)
    tasks.enqueue(event,now=now)
    assert tasks.claim(now=now+timedelta(seconds=300)) is None
    result=store.summaries(path,[event])[event['event_id']]
    assert result['review_state']=='STALE'
    assert result['deferred_reason']=='EXPIRED'


def test_credential_probe_exception_is_bounded_for_same_file(tmp_path,monkeypatch):
    h=Harness(tmp_path,monkeypatch)
    def fail(self,role):
        h.probes.append(role)
        raise ValueError('TEST_ONLY_DECRYPT_FAILURE')
    monkeypatch.setattr(h.arguments['client_factory'],'probe',fail)
    try:
        worker=h.start()
        wait_for(lambda:worker.state.get('access_blocker')=='PROBE_FAILED')
        sleep(.6)
        assert h.probes==['SOL'] and h.calls==[]
        assert worker.thread.is_alive()
    finally:
        h.close()
