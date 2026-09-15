"""Frozen daily-population DEV fit with per-chain checkpoints and stop deadline."""
import argparse
import datetime
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha, write_json

DEADLINE = datetime.datetime(2026, 9, 7, 18, tzinfo=datetime.timezone.utc)


class DeadlineReached(Exception):
    pass


def check_deadline(*_args, **_kwargs):
    if datetime.datetime.now(datetime.timezone.utc) >= DEADLINE:
        raise DeadlineReached('User requested stop deadline reached')


def main():
    global DEADLINE
    parser = argparse.ArgumentParser()
    parser.add_argument('--population', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--resume-from')
    parser.add_argument('--checkpoint')
    parser.add_argument('--deadline-utc')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    if bool(args.resume_from) != bool(args.checkpoint):
        raise ValueError('Resume requires an immutable pause checkpoint')
    if args.deadline_utc:
        DEADLINE = datetime.datetime.fromisoformat(args.deadline_utc)
        if DEADLINE.utcoffset() != datetime.timedelta(0):
            raise ValueError('Explicit UTC deadline required')
    source, out = (ROOT / args.population).resolve(), (ROOT / args.output).resolve()
    parent = ROOT / 'outputs/hybrid_delivery'
    if not source.is_relative_to(parent) or not out.is_relative_to(parent):
        raise ValueError('Independent DEV paths required')
    check_deadline()
    report = json.loads((source / 'report.json').read_text())
    if report['scope'] != 'DEV_ONLY' or report['execution_enabled'] or report['independent_oos']:
        raise ValueError('Authorized DEV population required')
    if sha(source / 'population.jsonl') != report['population_hash']:
        raise ValueError('Population hash mismatch')
    names = ['return_6h', 'er24', 'relative_volume24', 'relative_core24']
    config = {
        'version': 'population_student_t_dev_v1', 'scope': 'DEV_ONLY', 'exposure': 'EXPOSED_RESEARCH',
        'runtime_enabled': False, 'feature_order': names, 'population_hash': report['population_hash'],
        'selection': 'UTC midnight TRAIN rows only, no virtual-fill selection; first60% DEV with purge/24h embargo',
        'target': '100*log(1+24h gross return), NOT trade netR',
        'likelihood': 'StudentT with symbol:technical_mode partial pooling; nu=2+Exponential(.1)',
        'priors': {'alpha_sd': 2.0, 'beta_sd': 1.0, 'tau_halfnormal': 2.0, 'sigma_halfnormal': 5.0},
        'chains': 4, 'tune': 1000, 'draws': 1000, 'target_accept': .95,
        'chain_seeds': [202609071, 202609072, 202609073, 202609074],
        'prior_seed': 202609075, 'predictive_seed': 202609076, 'prior_draws': 500,
        'diagnostics': {'rhat_max': 1.01, 'ess_min': 400, 'divergences_max': 0},
        'missing': 'exclude, never impute', 'retries': 0,
        'support': 'log-return real line; exponentiated StudentT has no finite gross-return mean; never report it as expected simple return',
        'dependence': 'three coins share dates; conditional independence unverified, no market-calibration claim',
        'deadline': DEADLINE.isoformat(), 'deadline_policy': 'check each draw; retain finished chain artifacts on interruption',
        'code_hash': sha(Path(__file__)), 'command': sys.argv, 'interpreter': sys.executable}
    import numpy as np
    import pymc as pm
    import arviz as az
    rows = [json.loads(line) for line in (source / 'population.jsonl').read_text().splitlines()]
    rows = [r for r in rows if r['partition'] == 'TRAIN' and r['exclusion_reason'] is None]
    if not rows or any(r['feature_order'] != names or r['available_at'] > r['as_of']
                       or r['label_available_at'] >= report['boundary'] - 86400 for r in rows):
        raise ValueError('Training time or feature contract failure')
    x = np.asarray([r['x'] for r in rows], dtype=float)
    y = np.asarray([r['y_log_percent'] for r in rows], dtype=float)
    if not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError('Missing/nonfinite training population')
    mean, std = x.mean(axis=0), x.std(axis=0)
    std = np.where(std > 1e-12, std, 1.0)
    x = (x - mean) / std
    groups = sorted({r['symbol'] + ':' + r['mode'] for r in rows})
    index = np.asarray([groups.index(r['symbol'] + ':' + r['mode']) for r in rows])
    preprocessing = {'mean': mean.tolist(), 'std': std.tolist(),
        'groups': groups, 'feature_order': names, 'training_rows': len(rows),
        'dependency_dates': len({r['dependency_group'] for r in rows}),
        'group_counts': {g: sum(r['symbol'] + ':' + r['mode'] == g for r in rows) for g in groups}}
    completed = 0
    if args.resume_from:
        from kquant_crypto.hybrid_fit_resume import verify_resume, copy_verified_artifacts
        previous, checkpoint = (ROOT / args.resume_from).resolve(), (ROOT / args.checkpoint).resolve()
        if not previous.is_relative_to(parent) or not checkpoint.is_relative_to(parent):
            raise ValueError('Independent DEV resume paths required')
        completed = verify_resume(previous, checkpoint, config, rows, preprocessing)
    if args.verify_only:
        print(json.dumps({'resume_verified': bool(args.resume_from), 'completed_chains': completed,
                          'remaining_chains': 4 - completed, 'runtime_enabled': False}))
        return
    out.mkdir(exist_ok=False)
    write_json(out / 'preregistration.json', config)
    write_json(out / 'training_rows.json', rows)
    write_json(out / 'preprocessing.json', preprocessing)
    if completed:
        copy_verified_artifacts(previous, out, checkpoint, completed)
    started = time.monotonic()
    traces = [az.from_netcdf(out / f'chain_{i}.nc') for i in range(completed)]
    with pm.Model(coords={'feature': names, 'group': groups, 'observation': range(len(y))}) as model:
        alpha = pm.Normal('alpha', 0, 2.0)
        beta = pm.Normal('beta', 0, 1.0, dims='feature')
        tau = pm.HalfNormal('tau', 2.0)
        z = pm.Normal('z', 0, 1, dims='group')
        sigma = pm.HalfNormal('sigma', 5.0)
        nu = 2 + pm.Exponential('nu_minus_two', .1)
        mu = alpha + pm.math.dot(x, beta) + tau * z[index]
        pm.StudentT('outcome', nu=nu, mu=mu, sigma=sigma, observed=y, dims='observation')
        try:
            check_deadline()
            if completed:
                prior = az.from_netcdf(out / 'prior.nc')
            else:
                prior = pm.sample_prior_predictive(samples=500, random_seed=202609075)
                prior.to_netcdf(out / 'prior.nc')
            for chain, seed in enumerate(config['chain_seeds']):
                if chain < completed:
                    continue
                check_deadline()
                trace = pm.sample(draws=1000, tune=1000, chains=1, cores=1, random_seed=seed,
                    target_accept=.95, progressbar=False, callback=check_deadline)
                trace.to_netcdf(out / f'chain_{chain}.nc')
                traces.append(trace)
                write_json(out / 'progress.json', {'completed_chains': len(traces),
                    'elapsed_seconds': time.monotonic() - started, 'scope': 'DEV_ONLY',
                    'runtime_enabled': False, 'chain_hashes': {str(i): sha(out / f'chain_{i}.nc') for i in range(len(traces))}})
                print(json.dumps({'completed_chains': len(traces), 'required_chains': 4}), flush=True)
            check_deadline()
            trace = az.concat(*traces, dim='chain')
            pm.sample_posterior_predictive(trace, random_seed=202609076, extend_inferencedata=True, progressbar=False)
        except DeadlineReached:
            write_json(out / 'status.json', {'status': 'DEADLINE_PARTIAL', 'completed_chains': len(traces),
                'runtime_enabled': False, 'model_validated': False, 'resume_requires_explicit_user': True})
            print('DEADLINE_PARTIAL', flush=True)
            return
    trace.extend(prior)
    trace.to_netcdf(out / 'posterior.nc')
    summary = az.summary(trace, var_names=['alpha', 'beta', 'tau', 'sigma', 'nu_minus_two', 'z'], round_to='none')
    summary.to_csv(out / 'parameter_summary.csv')
    result = {'status': 'COMPLETED', 'training_rows': len(rows),
        'dependency_dates': len({r['dependency_group'] for r in rows}),
        'rhat_max': float(summary.r_hat.max()), 'ess_bulk_min': float(summary.ess_bulk.min()),
        'ess_tail_min': float(summary.ess_tail.min()), 'divergences': int(trace.sample_stats.diverging.sum()),
        'bfmi': az.bfmi(trace).tolist(), 'elapsed_seconds': time.monotonic() - started,
        'mean_validated': False, 'profit_probability_validated': False, 'tail_validated': False,
        'performance': 'PERFORMANCE_UNPROVEN', 'runtime_enabled': False}
    if 'reached_max_treedepth' in trace.sample_stats:
        result['max_depth_hits'] = int(trace.sample_stats.reached_max_treedepth.sum())
    for name, group in [('prior', trace.prior_predictive), ('posterior', trace.posterior_predictive)]:
        result[name + '_predictive_log_percent_quantiles'] = np.quantile(np.asarray(group.outcome), [.01, .5, .99]).tolist()
    write_json(out / 'diagnostics.json', result)
    write_json(out / 'artifact.json', {**config, 'posterior_sha256': sha(out / 'posterior.nc'), 'diagnostics': result})
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
