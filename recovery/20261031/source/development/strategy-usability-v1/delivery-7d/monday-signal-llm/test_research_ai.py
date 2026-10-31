"""TEST_ONLY transport and isolated budget ledger. No network or live credentials."""
import json
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from bootstrap import activate
HERE, _, _ = activate()
from kquant import options_research_ai as ai


class ResearchAI(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'TEST_ONLY_budget.sqlite3'
        self.config = json.loads((HERE/'config/research_ai.json').read_text())
        self.now = datetime(2026,10,18,6,tzinfo=UTC)
        self.receipt = dict(gate='O-SETUP',status='APPROVED',approved_by='OWNER',
            user_reply_id='TEST_ONLY_NOT_A_REAL_OWNER_REPLY',approval_id='TEST_ONLY',
            config_hash=ai.config_identity(self.config),approved_at='2026-10-18T05:00:00Z',
            capability_tests_allowed=True,live_paid_research_allowed=False)
        self.event = dict(event_id='TEST_ONLY_1',deadline_at='2026-10-18T06:05:00Z',
            bar_evidence=dict(open=10,high=12,low=9,close=11),option_cost={'cost':None})
        self.requests = []

    def tearDown(self):
        # The legacy helper uses connection contexts; release handles before Windows cleanup.
        import gc
        gc.collect()
        self.temp.cleanup()

    def transport(self, request):
        self.requests.append(request)
        output = ([dict(type='function_call',name='compute_price_components',
            arguments='{}',call_id='TEST_ONLY_CALL',id='TEST_ONLY_FUNC')] if len(self.requests)==1 else
            [dict(type='message',content=[dict(type='output_text',text=json.dumps(dict(
                support_refs=['bar_evidence'],opposing_refs=[],missing_inputs=['cost'],review_reasons=[])))])])
        return dict(id='TEST_ONLY_RESPONSE',model=ai.MODELS['SOL'],output=output,
            usage=dict(input_tokens=100,output_tokens=100))

    def client(self, **kwargs):
        return ai.ResponsesResearchClient(config=self.config,receipt=self.receipt,
            budget_path=self.path,transport=kwargs.pop('transport',self.transport),
            key_loader=lambda:None,clock=lambda:self.now,**kwargs)

    def test_unapproved_never_calls_or_opens_ledger(self):
        self.receipt={}
        result=self.client().assess(self.event,test_only=True)
        self.assertEqual(result['state'],'BUDGET_NOT_APPROVED')
        self.assertFalse(self.path.exists())
        self.assertEqual(self.requests,[])

    def test_tool_roundtrip_and_actual_usage(self):
        result=self.client().assess(self.event,test_only=True)
        self.assertEqual(result['state'],'COMPLETED',result)
        self.assertEqual(len(self.requests),2)
        self.assertEqual(result['actual_cost_usd'],'0.0024')
        self.assertFalse(result['qualified_signal'])
        self.assertEqual(result['tools'][0]['payload']['M'],1/3)
        self.assertTrue(any(x.get('type')=='function_call_output' for x in self.requests[1]['input']))

    def test_capability_acceptance_does_not_allow_live(self):
        self.assertEqual(self.client().assess(self.event)['state'],'BUDGET_NOT_APPROVED')

    def test_unknown_usage_holds_reservation(self):
        import requests
        def timeout(_):
            raise requests.Timeout('TEST_ONLY')
        result=self.client(transport=timeout).assess(self.event,test_only=True)
        self.assertIsNone(result['actual_cost_usd'])
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT state FROM llm_budget_reservations').fetchone()[0],'USAGE_UNKNOWN')

    def test_model_substitution_rejected(self):
        def wrong(request):
            response=self.transport(request)
            response['model']='NOT_THE_REQUESTED_MODEL'
            return response
        result=self.client(transport=wrong).assess(self.event,test_only=True)
        self.assertEqual(result['error_code'],'RETURNED_MODEL_MISMATCH')
        self.assertIsNone(result['actual_cost_usd'])
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT state FROM llm_budget_reservations').fetchone()[0],'USAGE_UNKNOWN')

    def test_tool_cannot_write(self):
        with self.assertRaises(ValueError):
            ai.tool_result('place_order',{},ai.evidence_packet(self.event))
        with self.assertRaises(ValueError):
            ai.tool_result('read_event_evidence',{'path':'other'},ai.evidence_packet(self.event))

    def test_repeat_event_does_not_call_again(self):
        client=self.client()
        client.assess(self.event,test_only=True)
        count=len(self.requests)
        result=client.assess(self.event,test_only=True)
        self.assertFalse(result['paid_call'])
        self.assertEqual(len(self.requests),count)

    def test_astra_exact_model_tool_roundtrip(self):
        def astra(request):
            self.assertEqual(request['model'],'gpt-6-astra')
            response=self.transport(request)
            response['model']='gpt-6-astra'
            return response
        result=self.client(transport=astra).assess(self.event,role='ASTRA',test_only=True)
        self.assertEqual(result['state'],'COMPLETED',result)
        self.assertEqual(result['actual_model'],'gpt-6-astra')
        self.assertEqual(result['actual_cost_usd'],'0.012')
        self.assertEqual(len(result['tools']),1)

    def test_astra_does_not_fallback_to_sol(self):
        result=self.client().assess(self.event,role='ASTRA',test_only=True)
        self.assertEqual(result['error_code'],'RETURNED_MODEL_MISMATCH')
        self.assertEqual(len(self.requests),1)

    def test_initial_budget_is_shared_between_models(self):
        # Unknown charged attempts retain their maximum bounds across both roles.
        import requests
        def timeout(_):
            raise requests.Timeout('TEST_ONLY')
        client=self.client(transport=timeout)
        first=client.assess(self.event,role='ASTRA',test_only=True)
        self.assertTrue(first['paid_call'])
        second=client.assess({**self.event,'event_id':'TEST_ONLY_2'},role='SOL',test_only=True)
        self.assertTrue(second['paid_call'])
        third=client.assess({**self.event,'event_id':'TEST_ONLY_3'},role='ASTRA',test_only=True)
        self.assertFalse(third['paid_call'])
        with sqlite3.connect(self.path) as db:
            held=db.execute("SELECT sum(CAST(reserved_usd AS REAL)) FROM llm_budget_reservations WHERE state='USAGE_UNKNOWN'").fetchone()[0]
        self.assertLessEqual(held,1)


if __name__=='__main__':
    unittest.main(verbosity=2)
