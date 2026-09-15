"""One preregistered multi-factor Student-t development fit, never runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False),encoding='utf-8')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    args = p.parse_args()
    out = (ROOT/args.output).resolve()
    if not out.is_relative_to(ROOT/'outputs/hybrid_delivery'):
        raise ValueError('Independent research path required')
    out.mkdir(exist_ok=False)
    source = ROOT/'outputs/hybrid_delivery/multifactor_entry_targets_20260907_01'
    report = json.loads((source/'report.json').read_text())
    if sha(source/'entry_targets.jsonl') != report['targets_hash']:
        raise ValueError('Target hash mismatch')
    names = ['return_6h','er24','relative_volume24','relative_core24']
    config = {'version':'multifactor_entry_student_t_dev_v1','scope':'DEV_ONLY',
        'exposure':'EXPOSED_RESEARCH','runtime_enabled':False,'feature_order':names,
        'selection':'A27 filled mature only; B185/unfilled excluded; no representative-population claim',
        'likelihood':'StudentT nu=2+Exponential(.1), alpha+beta*x+symbol_mode intercept',
        'priors':{'alpha_sd':.5,'beta_sd':.25,'tau_halfnormal':.5,'sigma_halfnormal':1.},
        'chains':4,'tune':1000,'draws':1000,'target_accept':.95,'seed':20260907,
        'prior_draws':500,'prior_seed':20260908,'predictive_seed':20260909,
        'diagnostics':{'rhat_max':1.01,'ess_min':400,'divergences_max':0},
        'dependence':'conditional independence unverified; only19 date groups and sparse range support',
        'retries':0,'validity':'No mean, profit-probability or tail validation granted',
        'target_hash':report['targets_hash'],'code_hash':sha(Path(__file__)),
        'command':sys.argv,'interpreter':sys.executable}
    dump(out/'preregistration.json',config)
    import numpy as np
    import pymc as pm
    import arviz as az
    rows = [json.loads(s) for s in (source/'entry_targets.jsonl').read_text().splitlines()]
    rows = [r for r in rows if r['fill_status']=='VIRTUAL_FILLED' and r['label_status']=='MATURE']
    if len(rows)!=27:
        raise ValueError('Unexpected selected population')
    values = [dict(r['feature_snapshot']['values'],**r['feature_snapshot']['cross_section']['values']) for r in rows]
    x = np.asarray([[r[k] for k in names] for r in values], dtype=float)
    y = np.asarray([r['net_r'] for r in rows])
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('Missing features must not be imputed')
    mean, std = x.mean(axis=0),x.std(axis=0)
    std = np.where(std>1e-12,std,1.)
    x = (x-mean)/std
    groups = sorted({r['symbol']+':'+r['mode'] for r in rows})
    index = np.asarray([groups.index(r['symbol']+':'+r['mode']) for r in rows])
    dump(out/'training_rows.json',rows)
    dump(out/'preprocessing.json',{'mean':mean.tolist(),'std':std.tolist(),'groups':groups,'feature_order':names})
    started = time.monotonic()
    with pm.Model(coords={'feature':names,'group':groups,'observation':range(len(y))}) as model:
        alpha = pm.Normal('alpha',0,.5)
        beta = pm.Normal('beta',0,.25,dims='feature')
        tau = pm.HalfNormal('tau',.5)
        z = pm.Normal('z',0,1,dims='group')
        sigma = pm.HalfNormal('sigma',1.)
        nu = 2+pm.Exponential('nu_minus_two',.1)
        mu = alpha+pm.math.dot(x,beta)+tau*z[index]
        pm.StudentT('outcome',nu=nu,mu=mu,sigma=sigma,observed=y,dims='observation')
        prior = pm.sample_prior_predictive(samples=500,random_seed=20260908)
        trace = pm.sample(draws=1000,tune=1000,chains=4,cores=1,random_seed=20260907,
                          target_accept=.95,progressbar=False)
        pm.sample_posterior_predictive(trace,random_seed=20260909,extend_inferencedata=True,progressbar=False)
    trace.extend(prior)
    trace.to_netcdf(out/'posterior.nc')
    summary = az.summary(trace,var_names=['alpha','beta','tau','sigma','nu_minus_two','z'],round_to='none')
    summary.to_csv(out/'parameter_summary.csv')
    diagnostics = {'rhat_max':float(summary.r_hat.max()),'ess_bulk_min':float(summary.ess_bulk.min()),
        'ess_tail_min':float(summary.ess_tail.min()),'divergences':int(trace.sample_stats.diverging.sum()),
        'bfmi':az.bfmi(trace).tolist(),'elapsed_seconds':time.monotonic()-started,
        'mean_validated':False,'profit_probability_validated':False,'tail_validated':False,
        'performance':'PERFORMANCE_UNPROVEN','runtime_enabled':False}
    if 'reached_max_treedepth' in trace.sample_stats:
        diagnostics['max_depth_hits'] = int(trace.sample_stats.reached_max_treedepth.sum())
    for name,group in [('prior',trace.prior_predictive),('posterior',trace.posterior_predictive)]:
        samples = np.asarray(group['outcome'])
        diagnostics[name+'_predictive_quantiles'] = np.quantile(samples,[.01,.5,.99]).tolist()
    dump(out/'diagnostics.json',diagnostics)
    dump(out/'artifact.json',dict(config,posterior_sha256=sha(out/'posterior.nc'),diagnostics=diagnostics))
    print(json.dumps(diagnostics))


if __name__ == '__main__':
    main()
