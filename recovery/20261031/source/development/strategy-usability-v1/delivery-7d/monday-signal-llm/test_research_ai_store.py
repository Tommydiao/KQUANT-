"""Real SQLite recovery and deduplication; all business records are TEST_ONLY."""
import gc
import json
import sqlite3
import tempfile
import unittest
from datetime import UTC,datetime,timedelta
from pathlib import Path
from bootstrap import activate
activate()
from kquant.options_research_ai import evidence_packet
from kquant import options_one_minute as common
from kquant import options_api_budget as budget
from kquant.options_research_ai_store import TaskStore,summaries,attach

class StoreTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.path=Path(self.temp.name)/'TEST_ONLY-copilot.sqlite3'
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE ai_assessments (assessment_id TEXT PRIMARY KEY,signal_id TEXT NOT NULL,material_state_hash TEXT NOT NULL,model_id TEXT NOT NULL,state TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL, UNIQUE(signal_id,material_state_hash,model_id))')
        self.store=TaskStore(self.path)
        self.now=datetime(2026,10,18,6,tzinfo=UTC)
        self.event=dict(event_id='TEST_ONLY_EVENT',evaluation_id='TEST_ONLY_EVALUATION',state='NUMERIC_PASS',
            input_revision=1,deadline_at=(self.now+timedelta(seconds=300)).isoformat(),
            reference_contract={'contract_id':'TEST_ONLY_CONTRACT','bid':1,'ask':1.1})

    def tearDown(self):
        gc.collect()
        self.temp.cleanup()

    def test_current_quote_refresh_does_not_repurchase_analysis(self):
        self.assertEqual(self.store.enqueue(self.event,now=self.now),'QUEUED')
        new={**self.event,'reference_contract':{**self.event['reference_contract'],'bid':1.01}}
        self.assertEqual(self.store.enqueue(new,now=self.now),'IDEMPOTENT')
        self.assertEqual(self.store.enqueue({**new,'input_revision':2},now=self.now),'QUEUED')
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM llm_work_queue WHERE state='QUEUED'").fetchone()[0],1)

    def test_sent_request_is_not_replayed_after_crash(self):
        self.store.enqueue(self.event,now=self.now)
        job=self.store.claim(now=self.now)
        reservation=budget.reserve_api_budget(scan_id='opening-ai:SOL:'+common.digest(evidence_packet(self.event)),
            worst_case_usd='.1',daily_limit_usd=5,timezone='Asia/Shanghai',approved=True,store_path=self.path)
        budget.mark_api_request_sent(reservation['reservation_id'],store_path=self.path)
        recovered=TaskStore(self.path)
        self.assertEqual(recovered.recover(now=self.now),1)
        self.assertIsNone(recovered.claim(now=self.now))
        with sqlite3.connect(self.path) as db:
            state,reason=db.execute('SELECT state,deferred_reason FROM llm_work_queue WHERE work_id=?',(job['work_id'],)).fetchone()
        self.assertEqual((state,reason),('DEFERRED','RECOVERY_USAGE_RECONCILIATION_REQUIRED'))

    def test_never_sent_pending_survives_reconstruction(self):
        self.store.enqueue(self.event,now=self.now)
        self.assertIsNotNone(self.store.claim(now=self.now))
        recovered=TaskStore(self.path)
        self.assertEqual(recovered.recover(now=self.now),1)
        self.assertIsNotNone(recovered.claim(now=self.now))

    def test_expired_queued_work_never_calls_model(self):
        self.store.enqueue(self.event,now=self.now)
        self.assertIsNone(self.store.claim(now=self.now+timedelta(seconds=301)))

    def test_result_attaches_to_same_event_and_preserves_rule_result(self):
        self.store.enqueue(self.event,now=self.now)
        job=self.store.claim(now=self.now)
        self.store.finish(job,dict(state='FAILED',delivery_state='MODEL_UNAVAILABLE',actual_cost_usd=None),now=self.now)
        row=dict(self.event)
        attach([row],path=self.path)
        self.assertEqual(row['state'],'NUMERIC_PASS')
        self.assertEqual(row['ai_review']['state'],'FAILED')
        self.assertEqual(row['ai_review']['display_state'],'SAME_EVALUATION')
        self.assertFalse(row['ai_review']['qualified_signal'])

    def test_no_sixth_store_created(self):
        with self.assertRaises(ValueError):
            TaskStore(Path(self.temp.name)/'MISSING.sqlite3')
        self.assertFalse((Path(self.temp.name)/'MISSING.sqlite3').exists())

if __name__=='__main__':
    unittest.main(verbosity=2)
