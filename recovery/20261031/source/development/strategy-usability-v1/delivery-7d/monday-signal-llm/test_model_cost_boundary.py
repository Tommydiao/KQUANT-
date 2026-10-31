"""Unexpected model usage cannot be settled at a different model's price."""
from contextlib import closing
import sqlite3
import unittest
import test_research_ai as fixture


class ModelCostBoundary(unittest.TestCase):
    def test_wrong_model_holds_unknown_cost(self):
        case=fixture.ResearchAI()
        case.setUp()
        try:
            def transport(request):
                response=case.transport(request)
                response['model']='TEST_ONLY_UNEXPECTED_MODEL'
                return response
            result=case.client(transport=transport).assess(case.event,test_only=True)
            self.assertEqual(result['error_code'],'RETURNED_MODEL_MISMATCH')
            self.assertIsNone(result['actual_cost_usd'])
            with closing(sqlite3.connect(case.path)) as db:
                state,cost=db.execute('SELECT state,actual_cost_usd FROM llm_budget_reservations').fetchone()
            self.assertEqual(state,'USAGE_UNKNOWN')
            self.assertIsNone(cost)
            calls=len(case.requests)
            case.client(transport=transport).assess(case.event,test_only=True)
            self.assertEqual(len(case.requests),calls)
        finally:
            case.tearDown()
