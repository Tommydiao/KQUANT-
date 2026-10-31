"""No paid model calls; transport is explicitly TEST_ONLY."""
import json
import unittest
import test_research_ai as fixture
from kquant.options_research_ai_worker import captured_event


class OutputBoundary(unittest.TestCase):
    def setUp(self):
        self.case=fixture.ResearchAI()
        self.case.setUp()

    def tearDown(self):
        self.case.tearDown()

    def test_unverified_free_text_is_not_a_review_code(self):
        def transport(request):
            value=self.case.transport(request)
            if value['output'][0]['type']=='message':
                payload=json.loads(value['output'][0]['content'][0]['text'])
                payload['review_reasons']=['TEST_ONLY_UNVERIFIED_99_PERCENT_WIN_RATE']
                value['output'][0]['content'][0]['text']=json.dumps(payload)
            return value
        result=self.case.client(transport=transport).assess(self.case.event,test_only=True)
        self.assertEqual(result['state'],'FAILED')
        self.assertEqual(result['error_code'],'UNSUPPORTED_ASSESSMENT_CODE')
        self.assertFalse(result['qualified_signal'])

    def test_old_strategy_cannot_be_manually_queued(self):
        original=dict(policy_id='TEST_ONLY_OLD_STRATEGY',state='NUMERIC_PASS',
            evaluation_id='TEST_ONLY_EVAL',event_id='TEST_ONLY_EVENT',runtime_inputs={'input_generation':1})
        revision={'reference_contract':{'contract_id':'TEST_ONLY_CONTRACT'},'revision':1}
        self.assertIsNone(captured_event(original,revision))
