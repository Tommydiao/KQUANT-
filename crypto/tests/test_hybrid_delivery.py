import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kquant_crypto.hybrid_delivery import Delivery, atomic_json, sha, lock


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ('plan', 'outputs/receipts', 'work'):
            (self.root / name).mkdir(parents=True)
        def task(i, deps=(), approval=None, scope='development'):
            return dict(id=i, title=i, acceptance=['proof'], depends_on=list(deps), requires_gates=[],
                        requires_approval=approval, scope=scope, priority=int(i[1:]))
        self.tasks = [task('T00'), task('T01', ['T00']), task('T02', ['T00']), task('T03', ['T02']),
                      task('T35', ['T00'], 'A1_TESTNET', 'testnet_only'), task('T51', [], None, 'owner_only')]
        atomic_json(self.root / 'plan/hybrid_to_live_tasks.v1_2.json', {'tasks': self.tasks})
        atomic_json(self.root / 'plan/hybrid_gate_policy.v1_2.json', {'gates': [{'id':'G0'}, {'id':'G1'}, {'id':'G7'}],
                    'aggregate_rules': {'ready_for_owner_live_approval_requires':['G7']}})
        atomic_json(self.root / 'outputs/proof.json', {'exit_code': 0})
        self.d = Delivery(self.root)

    def tearDown(self):
        self.d.close()
        self.temp.cleanup()

    def receipt(self, task, status='VERIFIED'):
        r = {'task_id':task, 'board_sha256':sha(self.d.board_path), 'status':status,
             'evidence':[{'path':'outputs/proof.json', 'sha256':sha(self.root / 'outputs/proof.json')}],
             'acceptance':{'proof':['outputs/proof.json']}, 'owner':'integration', 'reason':'waiting for natural labels',
             'blocked_scope':[task], 'next_trigger':'new qualified label'}
        p = f'outputs/receipts/{task}.json'
        atomic_json(self.root / p, r)
        return p

    def test_auto_progress_and_scoped_wait(self):
        self.d.record(self.receipt('T00'))
        self.d.record(self.receipt('T01','WAIT_DATA'))
        self.receipt('T02'); self.receipt('T03')
        result = self.d.run_ready('outputs/receipts')
        self.assertEqual(result['completed'], ['T02','T03'])
        self.assertEqual(self.d.status()['tasks']['T01']['status'], 'WAIT_DATA')

    def test_dependencies_cannot_be_skipped(self):
        with self.assertRaises(ValueError):
            self.d.record(self.receipt('T03'))

    def test_owner_and_testnet_cannot_be_self_approved(self):
        self.d.record(self.receipt('T00'))
        for t in ('T35','T51'):
            with self.assertRaises(ValueError):
                self.d.record(self.receipt(t))
        self.assertFalse(self.d.prepare_live_approval()['live_enabled'])

    def test_state_projection_not_authority(self):
        self.d.record(self.receipt('T00'))
        atomic_json(self.d.work / 'state.json', {'live_enabled':True, 'gates':{'G7':'PASS'}})
        self.assertFalse(self.d.status()['live_enabled'])
        self.assertEqual(self.d.prepare_live_approval()['status'], 'NOT_READY')
        self.d.project()
        self.assertFalse(json.loads((self.d.work / 'state.json').read_text())['live_enabled'])

    def test_evidence_change_invalidates_descendants(self):
        self.d.record(self.receipt('T00')); self.d.record(self.receipt('T02'))
        atomic_json(self.root / 'outputs/proof.json', {'exit_code':1})
        self.assertEqual(self.d.status()['tasks']['T02']['status'], 'BLOCKED_CONTRACT')

    def test_duplicate_receipt_no_duplicate_events(self):
        p = self.receipt('T00')
        self.assertTrue(self.d.record(p)); self.assertFalse(self.d.record(p))
        self.assertEqual(self.d.db.execute('SELECT count(*) FROM events').fetchone()[0],1)

    def test_crash_after_sql_commit_rebuilds_projection(self):
        with patch('kquant_crypto.hybrid_delivery.atomic_json', side_effect=OSError('disk')):
            with self.assertRaises(OSError): self.d.record(self.receipt('T00'))
        self.d.project()
        self.assertEqual(self.d.status()['tasks']['T00']['status'], 'VERIFIED')

    def test_lock_is_exclusive(self):
        with lock(self.d.work / 'locks/test.lock'):
            with self.assertRaises(OSError):
                with lock(self.d.work / 'locks/test.lock'): pass

    def test_pause_only_delivery_and_resume(self):
        self.d.pause(True)
        self.assertTrue(self.d.run_ready('outputs/receipts')['paused'])
        self.d.pause(False)
        self.assertFalse(self.d.status()['paused'])

    def test_version_change_fails_closed(self):
        atomic_json(self.d.board_path, {'tasks':[]})
        with self.assertRaises(ValueError): Delivery(self.root)

    def test_unsafe_evidence_path(self):
        for p in ('../secret', '.env', 'work/secrets.json'):
            with self.assertRaises(ValueError): self.d.safe_path(p)

    def test_retry_budget(self):
        self.d.record(self.receipt('T00'))
        p = self.receipt('T02')
        r = json.loads((self.root/p).read_text()); r['acceptance']={}
        atomic_json(self.root/p,r)
        for _ in range(5): self.d.run_ready('outputs/receipts')
        self.assertEqual(self.d.db.execute("SELECT count FROM attempts WHERE task='T02'").fetchone()[0],3)

    def test_torn_event_projection_recovered_without_losing_sql(self):
        self.d.record(self.receipt('T00'))
        p=self.d.work/'events.jsonl'; data=p.read_bytes();p.write_bytes(data[:30])
        self.d.project()
        self.assertEqual(p.read_bytes(),data)
        self.assertEqual(len(list(self.d.work.glob('events_torn_*'))),1)

    def test_conflicting_event_projection_not_silently_repaired(self):
        self.d.record(self.receipt('T00'))
        (self.d.work/'events.jsonl').write_text('{"fake":true}\n')
        with self.assertRaises(ValueError):self.d.project()

    def test_claim_conflict_and_release(self):
        self.d.record(self.receipt('T00'))
        self.d.claim('T02','worker',['kquant_crypto/new.py'])
        self.assertEqual(self.d.status()['tasks']['T02']['status'],'RUNNING')
        with self.assertRaises(ValueError):self.d.claim('T01','other',['kquant_crypto/new.py'])
        with self.assertRaises(ValueError):self.d.release('T02','other')
        self.d.release('T02','worker')
        self.assertEqual(self.d.status()['tasks']['T02']['status'],'READY')


if __name__ == '__main__': unittest.main()
