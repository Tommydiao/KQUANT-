import tempfile
from pathlib import Path
import unittest
from kquant_crypto.hybrid_experiment_registry_v12 import Registry, ARMS


def protocol():
    return dict(scope='SIMULATION_RESEARCH',primary_arm='T+B+M',arms=list(ARMS),symbols=['BTCUSDT','ETHUSDT','SOLUSDT'],
                execution_target='QUOTE_AWARE_SAMPLED_SIMULATION',strategy_hash='a'*64,cost_hash='b'*64,
                feature_hash='c'*64,risk_hash='d'*64,minimum_days=28,maximum_days=84,decision_checkpoint='FINAL_DAY_84_ONLY',
                weekly_performance_promotion=False,outcome_selected_end_date=False,historical_qualification='EXPOSED_RESEARCH',
                purge_overlap=True,embargo_seconds=21600,new_entry_filter_enabled=False,live_enabled=False,
                inherited_targets=dict(payoff=1.8,base_pf=1.3,double_cost_pf=1.05,mean_net_r_gt=0,
                                       portfolio_drawdown_max=.05,total_trades_min=200,per_mode_min=50,per_claimed_cell_min=30),
                ten_r_resolution=None,performance_blockers=['TEN_R_UNRESOLVED','CALIBRATION_POLICY_UNFROZEN'])


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(); self.r=Registry(Path(self.t.name)/'experiments.sqlite3')
        self.clock=dict(received_at_lower=1788603800.,received_at_upper=1788603800.5,clock_segment_id='clock')
    def tearDown(self): self.r.close();self.t.cleanup()
    def test_repeat_and_mutation(self):
        p=protocol(); h=self.r.register('v1',p,self.clock)
        self.assertEqual(h,self.r.register('v1',p,self.clock))
        p['feature_hash']='e'*64
        with self.assertRaises(ValueError): self.r.register('v1',p,self.clock)
    def test_old_data_and_target_rejected(self):
        self.r.register('v1',protocol(),self.clock)
        for t,target in [(1788603700.,'QUOTE_AWARE_SAMPLED_SIMULATION'),(1788603900.,'LEGACY_BAR_PROXY_BASE_10_5')]:
            with self.assertRaises(ValueError):
                self.r.start('v1',dict(available_at=t,qualified=True,execution_target=target))
    def test_d0_and_final_checkpoint_frozen(self):
        self.r.register('v1',protocol(),self.clock)
        e=dict(available_at=1788603900.,qualified=True,execution_target='QUOTE_AWARE_SAMPLED_SIMULATION')
        d0=self.r.start('v1',e)
        self.assertEqual(d0%86400,0);self.assertGreater(d0,e['available_at'])
        self.assertEqual(self.r.start('v1',e),d0)
        e['available_at']+=86400
        with self.assertRaises(ValueError):self.r.start('v1',e)
        self.assertEqual(self.r.report('v1')['final_decision_at'],d0+84*86400)
        self.assertFalse(self.r.report('v1')['live_enabled'])
    def test_no_silent_threshold_lowering(self):
        for key,value in [('weekly_performance_promotion',True),('new_entry_filter_enabled',True),('maximum_days',30),('performance_blockers',[])]:
            p=protocol();p[key]=value
            with self.assertRaises(ValueError):self.r.register('bad',p,self.clock)


if __name__=='__main__':unittest.main()
