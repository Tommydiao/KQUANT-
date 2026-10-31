import unittest
from copy import deepcopy
from datetime import UTC,datetime,timedelta
from threading import Event
from bootstrap import activate
activate()
from kquant.options_research_ai_lane import ResearchAILane,review_delivery

class LaneTest(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,18,6,tzinfo=UTC)
        self.event=dict(event_id='TEST_ONLY',state='NUMERIC_PASS',input_revision=1,
            deadline_at=(self.now+timedelta(seconds=100)).isoformat(),
            reference_contract={'snapshot':{'bbo_received_at':self.now.isoformat()}},
            live_price_check={'state':'PASS','checked_at':self.now.isoformat()})
        self.result={'state':'COMPLETED'}

    def test_quote_does_not_get_new_lifetime(self):
        result=review_delivery(self.result,self.event,self.event,now=self.now+timedelta(seconds=4))
        self.assertEqual(result['delivery_state'],'QUOTE_STALE')
        self.assertFalse(result['current_opportunity'])

    def test_revision_rejects_old_result(self):
        revised=deepcopy(self.event)
        revised['input_revision']=2
        self.assertEqual(review_delivery(self.result,self.event,revised,now=self.now)['delivery_state'],'INPUT_REVISED')

    def test_expiry(self):
        self.assertEqual(review_delivery(self.result,self.event,self.event,now=self.now+timedelta(seconds=101))['delivery_state'],'EXPIRED')

    def test_structure_check_required(self):
        current=deepcopy(self.event)
        current['live_price_check']['state']='FAIL'
        self.assertEqual(review_delivery(self.result,self.event,current,now=self.now)['delivery_state'],'PRICE_RECHECK_REQUIRED')

    def test_busy_and_model_failure_are_nonblocking(self):
        started,release=Event(),Event()
        class Client:
            def assess(_,event,role):
                started.set()
                release.wait(3)
                raise TimeoutError('TEST_ONLY')
        saved=[]
        lane=ResearchAILane(Client(),on_result=lambda event,result:saved.append(result),
            current_event=lambda identity:self.event,clock=lambda:self.now)
        try:
            self.assertEqual(lane.submit(self.event),'QUEUED')
            self.assertTrue(started.wait(1))
            self.assertEqual(lane.submit(self.event),'INFLIGHT')
            self.assertEqual(lane.submit({**self.event,'event_id':'ANOTHER'}),'DEFERRED_BUSY')
            self.assertIsNone(lane.poll())
            release.set()
            lane.active[1].exception(timeout=2)
            self.assertEqual(lane.poll()['delivery_state'],'MODEL_UNAVAILABLE')
            self.assertEqual(self.event['state'],'NUMERIC_PASS')
        finally:
            release.set()
            lane.close()

if __name__=='__main__':
    unittest.main(verbosity=2)
