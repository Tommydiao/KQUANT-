"""Freeze forward timing policy without starting evaluation or model consumers."""
import argparse
import asyncio
from dataclasses import asdict
from pathlib import Path
import sys
import time
import json

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import httpx
from run_hybrid_clock_observer import probes
from kquant_crypto.hybrid_clock import calibrate
from kquant_crypto.candidate_policy import load_policy
from kquant_crypto.hybrid_delivery import atomic_json, sha
from kquant_crypto.hybrid_experiment_registry_v12 import Registry, ARMS


async def run(out):
    out=(ROOT/out).resolve()
    if not out.is_relative_to(ROOT/'outputs/hybrid_delivery'): raise ValueError('Independent output required')
    out.mkdir(parents=True,exist_ok=False)
    p={'scope':'SIMULATION_RESEARCH','primary_arm':'T+B+M','arms':list(ARMS),
       'symbols':['BTCUSDT','ETHUSDT','SOLUSDT'],'execution_target':'QUOTE_AWARE_SAMPLED_SIMULATION',
       'strategy_hash':load_policy(candidate='A')['policy_hash'],
       'cost_hash':sha(ROOT/'config/dual_regime_candidate_v1.json'),
       'risk_hash':sha(ROOT/'config/dual_regime_candidate_v1.json'),
       'feature_hash':sha(ROOT/'kquant_crypto/hybrid_features.py'),
       'minimum_days':28,'maximum_days':84,'decision_checkpoint':'FINAL_DAY_84_ONLY',
       'weekly_performance_promotion':False,'outcome_selected_end_date':False,
       'historical_qualification':'EXPOSED_RESEARCH','purge_overlap':True,'embargo_seconds':21600,
       'new_entry_filter_enabled':False,'live_enabled':False,
       'inherited_targets':{'payoff':1.8,'base_pf':1.3,'double_cost_pf':1.05,'mean_net_r_gt':0,
                            'portfolio_drawdown_max':.05,'total_trades_min':200,'per_mode_min':50,'per_claimed_cell_min':30},
       'ten_r_resolution':None,'performance_blockers':['TEN_R_UNRESOLVED','CALIBRATION_POLICY_UNFROZEN','NO_MATCHING_TARGET_MODEL'],
       'historical_cutoff_utc':'2026-04-13T00:00:00Z','max_primary_models':1,'max_simple_baselines':1,'max_registered_challengers':1,
       'D0_rule':'Next full UTC day after first post-registration qualified event; not started by this CLI',
       'policy_approval':'DEVELOPMENT_REGISTRATION_NOT_FORMAL_MODEL_ADMISSION'}
    atomic_json(out/'protocol.json',p)
    async with httpx.AsyncClient(timeout=15,trust_env=False,follow_redirects=False) as client:
        sampled=await probes(client)
    atomic_json(out/'clock_probes.json',sampled)
    seg=calibrate(sampled)
    atomic_json(out/'clock_segment.json',asdict(seg))
    clock=seg.bounds(time.perf_counter(),time.time())
    registry=Registry(ROOT/'work/hybrid_delivery/experiments.sqlite3')
    try:
        registry.register('tbm_prospective_v12_registration_01',p,clock)
        report=registry.report('tbm_prospective_v12_registration_01')
        report.update({'registration_clock':clock,'model_gate_passed':False,'G7_passed':False,
                       'scope':'PROSPECTIVE_TIMING_ENGINEERING_ONLY','all_old_experiments_preserved':True,
                       'protocol_file_sha256':sha(out/'protocol.json')})
        atomic_json(out/'registration.json',report)
        print(json.dumps(report,indent=2))
    finally:registry.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    asyncio.run(run(a.output))
