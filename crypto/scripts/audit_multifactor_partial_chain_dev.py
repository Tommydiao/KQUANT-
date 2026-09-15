"""Single completed chain diagnostics; deliberately no Rhat or model admission."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha,write_json


def main():
    p=argparse.ArgumentParser();p.add_argument('--fit',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();fit=(ROOT/a.fit).resolve();out=(ROOT/a.output).resolve()
    if any(not path.is_relative_to(ROOT/'outputs/hybrid_delivery') for path in (fit,out)):
        raise ValueError('Independent research paths required')
    progress=json.loads((fit/'progress.json').read_text())
    source=fit/'chain_0.nc'
    if sha(source)!=progress['chain_hashes']['0']:
        raise ValueError('Completed chain hash mismatch')
    import arviz as az
    import numpy as np
    trace=az.from_netcdf(source)
    if trace.posterior.sizes.get('chain')!=1 or trace.posterior.sizes.get('draw')!=1000:
        raise ValueError('Expected one complete1000-draw chain')
    stats=trace.sample_stats
    result={'scope':'DEV_ONLY_PARTIAL_CHAIN','completed_chains_at_snapshot':progress['completed_chains'],
        'required_chains':4,'chain_sha256':sha(source),'draws':1000,
        'divergences':int(stats.diverging.sum()),'bfmi':az.bfmi(trace).tolist(),
        'rhat':None,'multichain_convergence_available':False,'complete_model':False,
        'mean_validated':False,'profit_probability_validated':False,'tail_validated':False,
        'performance':'PERFORMANCE_UNPROVEN','runtime_enabled':False}
    for key in ('tree_depth','n_steps','step_size','acceptance_rate'):
        if key in stats:
            values=np.asarray(stats[key]);result[key]={'mean':float(values.mean()),'max':float(values.max())}
    if 'reached_max_treedepth' in stats:result['max_depth_hits']=int(stats.reached_max_treedepth.sum())
    out.mkdir(exist_ok=False);write_json(out/'report.json',result);print(json.dumps(result))


if __name__=='__main__':main()
