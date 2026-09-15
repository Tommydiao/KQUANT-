"""Measure stored model load and one exposed snapshot inference, no online use."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha,write_json


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);args=p.parse_args()
    base=ROOT/'outputs/hybrid_delivery';out=(ROOT/args.output).resolve()
    if not out.is_relative_to(base) or out.exists():raise ValueError('New isolated output required')
    started=time.perf_counter()
    import numpy as np
    import arviz as az
    from scipy.stats import t
    import_seconds=time.perf_counter()-started
    model=base/'multifactor_population_fit_20260908_01'
    population=base/'multifactor_population_20260907_01/population.jsonl'
    forecasts=base/'multifactor_population_prediction_20260908_01'
    started=time.perf_counter()
    meta=json.loads((model/'artifact.json').read_text())
    if sha(model/'posterior.nc')!=meta['posterior_sha256'] or sha(population)!=meta['population_hash']:
        raise ValueError('Model/population changed')
    report=json.loads((forecasts/'report.json').read_text())
    if sha(forecasts/'predictions.jsonl')!=report['prediction_hash']:raise ValueError('Forecast changed')
    rows=[json.loads(line) for line in population.read_text().splitlines()]
    train=[r for r in rows if r['partition']=='TRAIN' and r['exclusion_reason'] is None]
    if train!=json.loads((model/'training_rows.json').read_text()):raise ValueError('Training identity changed')
    observed=json.loads((forecasts/'predictions.jsonl').read_text().splitlines()[0])
    row=next(r for r in rows if (r['symbol'],r['as_of'])==(observed['symbol'],observed['as_of']))
    if row['partition']!='DEVELOPMENT_DIAGNOSTIC' or row['exposure']!='EXPOSED_RESEARCH' or row['exclusion_reason'] is not None:
        raise ValueError('Only exposed diagnostic snapshot permitted')
    prep=json.loads((model/'preprocessing.json').read_text())
    xt=np.asarray([r['x'] for r in train]);std=xt.std(axis=0);std=np.where(std>1e-12,std,1.)
    if not np.array_equal(prep['mean'],xt.mean(axis=0)) or not np.array_equal(prep['std'],std):
        raise ValueError('Preprocessing not training-only')
    provenance_seconds=time.perf_counter()-started
    started=time.perf_counter();trace=az.from_netcdf(model/'posterior.nc');post=trace.posterior.stack(sample=('chain','draw'))
    alpha=np.asarray(post.alpha.transpose('sample'));beta=np.asarray(post.beta.transpose('sample','feature'))
    tau=np.asarray(post.tau.transpose('sample'));z=np.asarray(post.z.transpose('sample','group'))
    sigma=np.asarray(post.sigma.transpose('sample'));nu=2+np.asarray(post.nu_minus_two.transpose('sample'))
    load_seconds=time.perf_counter()-started
    if list(post.coords['feature'].values)!=prep['feature_order'] or list(post.coords['group'].values)!=prep['groups']:
        raise ValueError('Posterior order mismatch')
    group=prep['groups'].index(row['symbol']+':'+row['mode'])
    def infer():
        x=(np.asarray(row['x'])-prep['mean'])/std
        mu=alpha+beta@x+tau*z[:,group]
        return float(mu.mean()),float(t.sf(-mu/sigma,df=nu).mean())
    started=time.perf_counter();value=infer();first=time.perf_counter()-started
    reference=(observed['expected_log_percent'],observed['positive_gross_probability_uncalibrated'])
    if not np.allclose(value,reference,rtol=0,atol=1e-12):raise ValueError('Inference parity failed')
    durations=[]
    for _ in range(200):
        started=time.perf_counter();current=infer();durations.append(time.perf_counter()-started)
        if current!=value:raise ValueError('Deterministic inference changed')
    result=dict(scope='DEV_ONLY_EXPOSED_COMPUTE_BENCHMARK',posterior_hash=meta['posterior_sha256'],
        forecast_hash=report['prediction_hash'],snapshot=dict(symbol=row['symbol'],as_of=row['as_of']),
        import_seconds=import_seconds,provenance_verification_seconds=provenance_seconds,
        posterior_load_materialize_seconds=load_seconds,first_snapshot_inference_seconds=first,
        warm_repetitions=200,warm_seconds_p50_p95_p99=np.quantile(durations,[.5,.95,.99]).tolist(),
        parity_max_absolute_error=max(abs(a-b) for a,b in zip(value,reference)),
        clock='perf_counter, not offset wall clock',refit=False,runtime_enabled=False,
        numerical_gate='FAIL_EXISTING_DIVERGENCE',probability_calibrated=False,
        code_hash=sha(Path(__file__)),interpreter=sys.executable,
        limitation='One saved snapshot repeatedly measured, no network, feature ingestion, predictive interval sampling or MC. Concurrent MC worker active. Not end-to-end production latency or readiness; training duration is separate.')
    out.mkdir(exist_ok=False);write_json(out/'report.json',result);print(json.dumps(result))


if __name__=='__main__':main()
