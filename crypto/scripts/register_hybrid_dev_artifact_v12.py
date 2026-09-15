"""New conservative availability attestation; never backdates the old model."""
import argparse
import asyncio
from pathlib import Path
import sys
import time
import json

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import httpx
from run_hybrid_clock_observer import probes
from kquant_crypto.hybrid_clock import calibrate
from kquant_crypto.hybrid_posterior_review import verify_frozen, FROZEN
from kquant_crypto.hybrid_delivery import atomic_json, sha


async def run(output):
    output=(ROOT/output).resolve()
    if not output.is_relative_to(ROOT/'outputs/hybrid_delivery'):raise ValueError('Independent output only')
    output.mkdir(parents=True,exist_ok=False)
    # File existed and matched before the upper-bound observation. This is a
    # new research registration, not a correction to original build timestamps.
    async with httpx.AsyncClient(timeout=15,trust_env=False,follow_redirects=False) as client:
        samples=await probes(client)
    segment=calibrate(samples)
    hashes=verify_frozen()
    clock=segment.bounds(time.perf_counter(),time.time())
    record={'schema':'hybrid_dev_artifact_availability_v12','scope':'DEV_ONLY',
            'artifact_path':str(FROZEN.relative_to(ROOT)),'artifact_hash':hashes['artifact.json'],
            'posterior_sha256':hashes['posterior.nc'],'verified_available_by':clock['received_at_upper'],
            'earliest_actual_creation_time_verified':None,'new_registration_clock':clock,
            'original_model_times_unchanged':True,'original_timestamps_backfilled':False,
            'not_valid_for_predictions_before':clock['received_at_upper'],
            'execution_target':'LEGACY_BAR_PROXY_BASE_10_5','exposure':'EXPOSED_RESEARCH',
            'mean_inference_valid':False,'predictive_probability_valid':False,'predictive_tail_valid':False,
            'runtime_enabled':False,'admission':'ABSTAIN','G2_passed':False,
            'clock_probes_sha256':None,'python':sys.executable}
    atomic_json(output/'clock_probes.json',samples)
    record['clock_probes_sha256']=sha(output/'clock_probes.json')
    atomic_json(output/'availability.json',record)
    print(json.dumps(record,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    asyncio.run(run(a.output))
