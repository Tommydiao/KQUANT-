from contextlib import closing
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from bootstrap import activate
HERE,_,_=activate()
from kquant import options_one_minute as common
from kquant import options_opening_trend_store as store
from kquant import options_intraday_comparison as comparison
from kquant.options_opening_momentum import load_policy
from kquant.recovery_runtime_probe import schema_observation,SOURCE_INDEX_SCHEMA,CURRENT_INDEX_SCHEMA,COPILOT_BUDGET_BASE_SQL

class CurrentProjectionTest(unittest.TestCase):
    def test_real_saved_s1_card_expiry_watermark_and_current_index(self):
        args=json.loads((HERE/'evidence/real-btdr-input.json').read_text(encoding='utf-8'))['arguments']
        for key in ('opening','closing','now','checkpoint'):
            args[key]=common.timestamp(args[key])
        rows=comparison.evaluate_comparison_pair(**args)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'TEST_ONLY-research.sqlite3'
            store.initialize(path)
            from kquant.options_opening_momentum_journal import initialize
            initialize(path)
            store.persist(rows,path)
            with patch('kquant.options_research_ai_store.summaries',return_value={}):
                value=store.current_cards(path=path,session='2026-10-15',scope_hash=args['scope_hash'],now=args['now'],policy=load_policy())
                self.assertEqual(len(value['evaluations']),1)
                self.assertEqual(value['evaluations'][0]['strategy_comparison']['s1']['state'],'NUMERIC_PASS')
                self.assertEqual(value['candidates'],[])
                self.assertIsNotNone(value['current_projection']['source_watermark']['evaluation_rowid'])
                after=store.current_cards(path=path,session='2026-10-15',scope_hash=args['scope_hash'],now=args['checkpoint']+timedelta(seconds=301),policy=load_policy())
                self.assertEqual(after['evaluations'],[])
            with closing(sqlite3.connect(path)) as db:
                plan=db.execute('EXPLAIN QUERY PLAN SELECT evaluation_id FROM evaluations WHERE policy_hash=? AND session=? AND julianday(evaluated_at)>=julianday(?)',('p','s','2026-10-15')).fetchall()
                self.assertTrue(any('trend_current_time' in row[-1] for row in plan))

    def test_exact_additive_indexes_do_not_allow_definition_changes(self):
        schema=[SOURCE_INDEX_SCHEMA,CURRENT_INDEX_SCHEMA]
        request={'role':'opening_research','schema_extension':'OPENING_SOURCE_AND_CURRENT_INDEX_V1'}
        expected=schema_observation([],{'role':'opening_research'})['schema_sha256']
        self.assertEqual(schema_observation(schema,request)['baseline_schema_sha256'],expected)
        bad=[SOURCE_INDEX_SCHEMA,(*CURRENT_INDEX_SCHEMA[:3],'CREATE INDEX trend_current_time ON evaluations(session)')]
        with self.assertRaisesRegex(ValueError,'DECLARED_INDEX_DEFINITION_CHANGED'):
            schema_observation(bad,request)

    def test_budget_queue_migration_preserves_original_schema_proof(self):
        from kquant.options_api_budget import initialize_api_budget_store
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'TEST_ONLY-copilot.sqlite3'
            with closing(sqlite3.connect(path)) as db,db:
                db.execute(COPILOT_BUDGET_BASE_SQL)
                db.execute("CREATE TABLE llm_budget_days (budget_date TEXT NOT NULL,timezone TEXT NOT NULL,daily_limit_usd TEXT NOT NULL,settled_usd TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(budget_date,timezone))")
                db.execute('CREATE INDEX idx_llm_budget_reservations_day ON llm_budget_reservations(budget_date, timezone, state)')
                before=db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
            baseline=schema_observation(before,{'role':'signal_copilot'})['schema_sha256']
            initialize_api_budget_store(store_path=path)
            with closing(sqlite3.connect(path)) as db:
                after=db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
            request={'role':'signal_copilot','schema_extension':'COPILOT_AI_BUDGET_QUEUE_V1'}
            self.assertEqual(schema_observation(after,request)['baseline_schema_sha256'],baseline)
            changed=[(*r[:3],r[3].replace('DEFAULT \'ASTRA\'','DEFAULT \'OTHER\'')) if r[1]=='llm_budget_reservations' else r for r in after]
            with self.assertRaisesRegex(ValueError,'DECLARED_AI_BUDGET_COLUMNS_CHANGED'):
                schema_observation(changed,request)

if __name__=='__main__':
    unittest.main(verbosity=2)
