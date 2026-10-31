import json
import sqlite3
import unittest
from copy import deepcopy
from bootstrap import activate
HERE, _, _=activate()
from kquant import options_intraday_comparison as comparison
from kquant import options_one_minute as common

class IndependentReferenceTest(unittest.TestCase):
    def test_cross_day_failure_preserves_real_s1(self):
        args=json.loads((HERE/'evidence/real-btdr-input.json').read_text(encoding='utf-8'))['arguments']
        for key in ('opening','closing','now','checkpoint'):
            args[key]=common.timestamp(args[key])
        original=deepcopy(args['reference'])
        def unavailable(*a,**k):
            raise sqlite3.OperationalError('TEST_ONLY_CROSS_DAY_LOCK')
        args['reference']=comparison.independent_reference(original,unavailable)
        result=comparison.evaluate_comparison_pair(**args)
        self.assertEqual([x['state'] for x in result],['INCOMPLETE','INCOMPLETE'])
        self.assertEqual([x['strategy_comparison']['s1']['state'] for x in result],['NO_TRIGGER','NUMERIC_PASS'])
        self.assertEqual(original['raw_quote'],args['reference']['raw_quote'])
        self.assertIsNone(args['reference']['previous_close'])

    def test_unknown_bug_not_hidden(self):
        def broken(*a,**k):
            raise TypeError('TEST_ONLY_PROGRAM_ERROR')
        with self.assertRaises(TypeError):
            comparison.independent_reference({},broken)

    def test_success_is_unmodified(self):
        expected={'contract_version':'TEST_ONLY'}
        self.assertIs(comparison.independent_reference({},lambda *a,**k:expected),expected)

if __name__=='__main__':
    unittest.main(verbosity=2)
