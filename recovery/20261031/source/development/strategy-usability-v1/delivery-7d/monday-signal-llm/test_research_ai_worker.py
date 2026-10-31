"""Actual worker constructor/thread/storage with explicit TEST_ONLY model transport."""
from contextlib import closing
from datetime import UTC,datetime,timedelta
import gc
import json
from pathlib import Path
import sqlite3
import tempfile
from threading import Event
from time import monotonic,sleep
import unittest
from unittest.mock import patch
from bootstrap import activate
HERE,_,_=activate()
from kquant.options_research_ai import config_identity
from kquant.options_research_ai_store import summaries
from kquant.options_research_ai_worker import ResearchAIWorker

class WorkerTest(unittest.TestCase):
    def test_astra_access_failure_is_cached_without_blocking_sol(self):
        from kquant.options_research_ai_store import TaskStore
        from kquant.options_research_ai_worker import captured_event
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            research,copilot=root/'TEST_ONLY-research.sqlite3',root/'TEST_ONLY-copilot.sqlite3'
            now=datetime(2026,10,19,13,35,1,tzinfo=UTC)
            with closing(sqlite3.connect(copilot)) as db,db:
                db.execute('CREATE TABLE ai_assessments(assessment_id TEXT PRIMARY KEY,signal_id TEXT,material_state_hash TEXT,model_id TEXT,state TEXT,payload_json TEXT,created_at TEXT,UNIQUE(signal_id,material_state_hash,model_id))')
            tasks=TaskStore(copilot)
            with closing(sqlite3.connect(research)) as db,db:
                db.executescript('CREATE TABLE evaluations(evaluation_id TEXT PRIMARY KEY,evaluated_at TEXT,payload_json TEXT); CREATE TABLE revisions(revision_id INTEGER PRIMARY KEY,evaluation_id TEXT,payload_json TEXT); CREATE TABLE qualified_claims(evaluation_id TEXT,payload_json TEXT);')
                for index,role in enumerate(('ASTRA','ASTRA','SOL')):
                    original=dict(event_id='TEST_ONLY_EVENT_'+str(index),evaluation_id='TEST_ONLY_EVAL_'+str(index),
                        symbol='TEST_ONLY',right='CALL',policy_id='STRAT-INTRADAY-MOMENTUM-S1-RESEARCH-V1',
                        state='NUMERIC_PASS',deadline_at=(now+timedelta(seconds=299)).isoformat(),
                        runtime_inputs={'input_generation':1},bar_evidence=dict(open=10,high=12,low=9,close=11),
                        structure_line=9,entry_range=[11,11.5])
                    revision=dict(state='PENDING',checked_at=now.isoformat(),revision=index+1,
                        reference_contract={'contract_id':'TEST_ONLY_CONTRACT','snapshot':{'bbo_received_at':now.isoformat()}},
                        underlying_quote={'last':11,'received_at':now.isoformat()})
                    db.execute('INSERT INTO evaluations VALUES(?,?,?)',(original['evaluation_id'],now.isoformat(),json.dumps(original)))
                    db.execute('INSERT INTO revisions VALUES(?,?,?)',(index+1,original['evaluation_id'],json.dumps(revision)))
                    tasks.enqueue(captured_event(original,revision),role=role,now=now)
            config=json.loads((HERE/'config/research_ai.json').read_text(encoding='utf-8'))
            config_path,receipt_path=root/'TEST_ONLY-config.json',root/'TEST_ONLY-receipt.json'
            config_path.write_text(json.dumps(config),encoding='utf-8')
            receipt_path.write_text(json.dumps(dict(gate='O-SETUP',status='APPROVED',approved_by='OWNER',
                user_reply_id='TEST_ONLY_NOT_REAL_ACCEPTANCE',config_hash=config_identity(config),
                approved_at='2026-10-18T06:00:00Z',capability_tests_allowed=True,live_paid_research_allowed=True)),encoding='utf-8')
            cursor=root/'TEST_ONLY-cursor.json'
            cursor.write_text(json.dumps(dict(revision_id=3,source_path=str(research.resolve()))),encoding='utf-8')
            key=root/'TEST_ONLY-key-marker'
            key.write_text('TEST_ONLY_NOT_A_KEY',encoding='utf-8')
            probes,calls=[],[]
            class Client:
                def __init__(self,**kwargs): pass
                def probe(self,role):
                    probes.append(role)
                    return {'state':'NOT_ACCESSIBLE' if role=='ASTRA' else 'ACCESSIBLE','test_only':True}
                def assess(self,event,role):
                    calls.append(role)
                    return {'state':'FAILED','error_code':'TEST_ONLY_MODEL_RESULT','actual_cost_usd':None,'test_only':True}
            class Hub:
                def __init__(self): self.events=[]
                def publish(self,event): self.events.append(event)
            hub=Hub()
            with patch('kquant.options_research_ai_worker.credential_path',return_value=key):
                worker=ResearchAIWorker(research_path=research,copilot_path=copilot,config_path=config_path,
                    receipt_path=receipt_path,cursor_path=cursor,hub=hub,clock=lambda:now,client_factory=Client)
                try:
                    until=monotonic()+4
                    while len(hub.events)<3 and monotonic()<until:
                        sleep(.02)
                    self.assertEqual(len(hub.events),3,worker.state)
                    self.assertEqual(calls,['SOL'])
                    self.assertEqual(probes.count('ASTRA'),1)
                    self.assertEqual(probes.count('SOL'),1)
                    self.assertTrue(worker.thread.is_alive())
                finally:
                    worker.close()
            gc.collect()

    def test_model_mismatch_stops_more_calls_for_same_credential(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            research,copilot=root/'TEST_ONLY-research.sqlite3',root/'TEST_ONLY-copilot.sqlite3'
            now=datetime(2026,10,19,13,35,1,tzinfo=UTC)
            with closing(sqlite3.connect(research)) as db,db:
                db.executescript('CREATE TABLE evaluations(evaluation_id TEXT PRIMARY KEY,evaluated_at TEXT,payload_json TEXT); CREATE TABLE revisions(revision_id INTEGER PRIMARY KEY,evaluation_id TEXT,payload_json TEXT); CREATE TABLE qualified_claims(evaluation_id TEXT,payload_json TEXT);')
                for index in range(2):
                    original=dict(event_id='TEST_ONLY_EVENT_'+str(index),evaluation_id='TEST_ONLY_EVAL_'+str(index),
                        symbol='TEST_ONLY',right='CALL',policy_id='STRAT-INTRADAY-MOMENTUM-S1-RESEARCH-V1',
                        state='NUMERIC_PASS',deadline_at=(now+timedelta(seconds=299)).isoformat(),
                        runtime_inputs={'input_generation':1},bar_evidence=dict(open=10,high=12,low=9,close=11),
                        structure_line=9,entry_range=[11,11.5])
                    revision=dict(state='PENDING',checked_at=now.isoformat(),
                        reference_contract={'contract_id':'TEST_ONLY_CONTRACT','snapshot':{'bbo_received_at':now.isoformat()}},
                        underlying_quote={'last':11,'received_at':now.isoformat()})
                    db.execute('INSERT INTO evaluations VALUES(?,?,?)',(original['evaluation_id'],now.isoformat(),json.dumps(original)))
                    db.execute('INSERT INTO revisions VALUES(?,?,?)',(index+1,original['evaluation_id'],json.dumps(revision)))
            with closing(sqlite3.connect(copilot)) as db,db:
                db.execute('CREATE TABLE ai_assessments(assessment_id TEXT PRIMARY KEY,signal_id TEXT,material_state_hash TEXT,model_id TEXT,state TEXT,payload_json TEXT,created_at TEXT,UNIQUE(signal_id,material_state_hash,model_id))')
            config=json.loads((HERE/'config/research_ai.json').read_text(encoding='utf-8'))
            config_path,receipt_path=root/'TEST_ONLY-config.json',root/'TEST_ONLY-receipt.json'
            config_path.write_text(json.dumps(config),encoding='utf-8')
            receipt_path.write_text(json.dumps(dict(gate='O-SETUP',status='APPROVED',approved_by='OWNER',
                user_reply_id='TEST_ONLY_NOT_REAL_ACCEPTANCE',config_hash=config_identity(config),
                approved_at='2026-10-18T06:00:00Z',capability_tests_allowed=True,live_paid_research_allowed=True)),encoding='utf-8')
            key=root/'TEST_ONLY-key-marker'
            key.write_text('TEST_ONLY_NOT_A_KEY',encoding='utf-8')
            calls=[]
            class Client:
                def __init__(self,**kwargs): pass
                def probe(self,role): return {'state':'ACCESSIBLE','test_only':True}
                def assess(self,event,role):
                    calls.append(event['evaluation_id'])
                    return {'state':'FAILED','error_code':'RETURNED_MODEL_MISMATCH','actual_cost_usd':None,'test_only':True}
            class Hub:
                def __init__(self): self.events=[]
                def publish(self,event): self.events.append(event)
            hub=Hub()
            with patch('kquant.options_research_ai_worker.credential_path',return_value=key):
                worker=ResearchAIWorker(research_path=research,copilot_path=copilot,config_path=config_path,
                    receipt_path=receipt_path,cursor_path=root/'TEST_ONLY-cursor.json',hub=hub,
                    clock=lambda:now,client_factory=Client)
                try:
                    until=monotonic()+3
                    while not worker.state.get('access_blocker') and monotonic()<until:
                        sleep(.02)
                    self.assertEqual(worker.state.get('access_blocker'),'RETURNED_MODEL_MISMATCH',worker.state)
                    sleep(.65)
                    self.assertEqual(len(calls),1)
                    self.assertTrue(worker.thread.is_alive())
                    self.assertTrue(hub.events)
                    with closing(sqlite3.connect(copilot)) as db:
                        self.assertEqual(db.execute("SELECT count(*) FROM llm_work_queue WHERE state='QUEUED'").fetchone()[0],1)
                finally:
                    worker.close()
            gc.collect()

    def test_real_revision_enqueue_complete_and_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            research,copilot=root/'TEST_ONLY-research.sqlite3',root/'TEST_ONLY-copilot.sqlite3'
            now=datetime(2026,10,19,13,35,1,tzinfo=UTC)
            with closing(sqlite3.connect(research)) as db,db:
                db.executescript('CREATE TABLE evaluations (evaluation_id TEXT PRIMARY KEY,evaluated_at TEXT,payload_json TEXT); CREATE TABLE revisions (revision_id INTEGER PRIMARY KEY,evaluation_id TEXT,payload_json TEXT); CREATE TABLE qualified_claims(evaluation_id TEXT,payload_json TEXT);')
                original=dict(event_id='TEST_ONLY_EVENT',evaluation_id='TEST_ONLY_EVAL',symbol='TEST_ONLY',right='CALL',
                    policy_id='STRAT-INTRADAY-MOMENTUM-S1-RESEARCH-V1',state='NUMERIC_PASS',research_strategy='opening_momentum',
                    deadline_at=(now+timedelta(seconds=299)).isoformat(),bar_evidence=dict(open=10,high=12,low=9,close=11),
                    runtime_inputs={'input_generation':1},structure_line=9,entry_range=[11,11.5])
                revision=dict(state='PENDING',checked_at=now.isoformat(),reference_contract={'contract_id':'TEST_ONLY_CONTRACT',
                    'snapshot':{'bbo_received_at':now.isoformat()}},underlying_quote={'last':11,'received_at':now.isoformat()})
                db.execute('INSERT INTO evaluations VALUES (?,?,?)',(original['evaluation_id'],now.isoformat(),json.dumps(original)))
                db.execute('INSERT INTO revisions VALUES (1,?,?)',(original['evaluation_id'],json.dumps(revision)))
            with closing(sqlite3.connect(copilot)) as db,db:
                db.execute('CREATE TABLE ai_assessments(assessment_id TEXT PRIMARY KEY,signal_id TEXT,material_state_hash TEXT,model_id TEXT,state TEXT,payload_json TEXT,created_at TEXT,UNIQUE(signal_id,material_state_hash,model_id))')
            config=json.loads((HERE/'config/research_ai.json').read_text(encoding='utf-8'))
            config_path=root/'TEST_ONLY-config.json'
            config_path.write_text(json.dumps(config),encoding='utf-8')
            receipt_path=root/'TEST_ONLY-receipt.json'
            receipt_path.write_text(json.dumps(dict(gate='O-SETUP',status='APPROVED',approved_by='OWNER',
                user_reply_id='TEST_ONLY_NOT_A_REAL_ACCEPTANCE',config_hash=config_identity(config),
                approved_at='2026-10-18T06:00:00Z',capability_tests_allowed=True,live_paid_research_allowed=True)),encoding='utf-8')
            key=root/'TEST_ONLY-key-marker'
            key.write_text('TEST_ONLY_NOT_A_CREDENTIAL',encoding='utf-8')
            called,release=Event(),Event()
            calls=[]
            class Client:
                def __init__(self,**kwargs): pass
                def probe(self,role): return {'state':'ACCESSIBLE','test_only':True}
                def assess(self,event,role):
                    calls.append(event['evaluation_id'])
                    called.set()
                    release.wait(3)
                    return {'state':'COMPLETED','assessment':{'support_refs':['bar_evidence'],'opposing_refs':[],'missing_inputs':[],'review_reasons':[]},'test_only':True,'actual_cost_usd':None}
            class Hub:
                def __init__(self): self.events=[]
                def publish(self,value): self.events.append(value)
            hub=Hub()
            arguments=dict(research_path=research,copilot_path=copilot,config_path=config_path,
                receipt_path=receipt_path,cursor_path=root/'TEST_ONLY-cursor.json',hub=hub,clock=lambda:now,client_factory=Client)
            with patch('kquant.options_research_ai_worker.credential_path',return_value=key):
                worker=ResearchAIWorker(**arguments)
                try:
                    self.assertTrue(called.wait(3),worker.state)
                    # A pending model does not prevent independent source reads.
                    self.assertEqual(len(worker.read_revisions(0)),1)
                    self.assertTrue(worker.thread.is_alive())
                    release.set()
                    until=monotonic()+3
                    while not hub.events and monotonic()<until:
                        sleep(.02)
                    self.assertTrue(hub.events,worker.state)
                    self.assertEqual(hub.events[0]['delivery_state'],'CURRENT_RESEARCH_REVIEW')
                    self.assertFalse(hub.events[0]['qualified_signal'])
                    self.assertEqual(summaries(copilot,[original])['TEST_ONLY_EVENT']['state'],'COMPLETED')
                finally:
                    release.set()
                    worker.close()
                restarted=ResearchAIWorker(**arguments)
                try:
                    until=monotonic()+1
                    while restarted.state['state']=='STARTING' and monotonic()<until:
                        sleep(.02)
                    self.assertEqual(calls,['TEST_ONLY_EVAL'])
                    self.assertEqual(restarted.state.get('recovered'),0)
                finally:
                    restarted.close()
            gc.collect()

if __name__=='__main__':
    unittest.main(verbosity=2)
