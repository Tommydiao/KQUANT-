"""TEST_ONLY actual snapshot pump, no SDK, model, server, or private credentials."""
from copy import deepcopy
from datetime import UTC,datetime
from time import monotonic,sleep
import unittest
from bootstrap import activate
activate()
from kquant.research_http_snapshots import ResearchHttpSnapshots
from kquant.options_one_minute import NY


class SnapshotDelivery(unittest.TestCase):
    def changed_payload_notifies(self,field):
        now=datetime.now(UTC)
        day=now.astimezone(NY).date().isoformat()
        state={'ai':'QUEUED','revision':1}
        notified=[]
        def loader(*args):
            return {'session':day,'evaluations':[{'evaluation_id':'TEST_ONLY_PARENT','event_id':'TEST_ONLY_PARENT_EVENT',
                'state':'INCOMPLETE','current_eligibility':{'state':'PENDING'},
                'strategy_comparison':{'s1':{'evaluation_id':'TEST_ONLY_CHILD','event_id':'TEST_ONLY_CHILD_EVENT',
                    'state':'NUMERIC_PASS','ai_review':{'state':state['ai'],'model':'gpt-6.1-sol',
                        'input_hash':'TEST_ONLY_HASH','created_at':now.isoformat()}},
                    'reference_eligibility':{'state':'PENDING','revision':state['revision'],'checked_at':now.isoformat()}}}],
                'candidates':[]}
        snapshots=ResearchHttpSnapshots(lambda:{'session':day,'scope_hash':'TEST_ONLY_SCOPE'},loader,
            lambda:{'state':'TEST_ONLY','enforced':False},on_complete=lambda strategy:notified.append(strategy),
            strategy_availability=lambda strategy:{'enabled':strategy=='opening_momentum'},clock=lambda:now)
        snapshots.start()
        try:
            until=monotonic()+3
            while not notified and monotonic()<until:
                sleep(.02)
            self.assertTrue(notified,'INITIAL_SNAPSHOT_NOT_PUBLISHED')
            sleep(.3)
            notified.clear()
            state[field]='COMPLETED' if field=='ai' else 2
            snapshots.invalidate('opening_momentum')
            until=monotonic()+2
            while not notified and monotonic()<until:
                sleep(.02)
            current=snapshots.caches['opening_momentum','current'].value
            self.assertEqual(current['evaluations'][0]['strategy_comparison']['s1']['ai_review']['state'],state['ai'])
            self.assertEqual(current['evaluations'][0]['strategy_comparison']['reference_eligibility']['revision'],state['revision'])
            self.assertTrue(notified,'FRESH_NESTED_CHANGE_NOT_PUBLISHED')
        finally:
            snapshots.close()

    def test_late_ai_result_emits_fresh_snapshot(self):
        self.changed_payload_notifies('ai')

    def test_s1_reference_revision_emits_fresh_snapshot(self):
        self.changed_payload_notifies('revision')
