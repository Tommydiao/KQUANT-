"""Isolated, explicitly exposed-development Student-t research fit."""

import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'outputs/hybrid_regime_v1/m2_development_20260905_04'
CONFIG = ROOT / 'config/hybrid_dev_fit_v1.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False), encoding='utf-8')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def index_rows(rows):
    result = {r['economic_signal_id']: r for r in rows}
    require(len(result) == len(rows), 'duplicate economic signal')
    return result


def base_r(label, opportunity):
    t, p = label['executed_trade'], opportunity['plan']
    fee, slip = 0.001, 0.0005
    entry, stop = p['entry_reference'] * (1 + slip), p['stop'] * (1 - slip)
    risk = entry - stop + fee * (entry + stop)
    close = lambda a, b: math.isclose(a, b, rel_tol=1e-8, abs_tol=1e-8)
    require(math.isfinite(risk) and risk > 0 and t['quantity'] > 0, 'invalid BASE denominator')
    require(close(risk, p['unit_net_risk']) and close(risk, t['unit_net_risk']), 'BASE risk mismatch')
    # Signal-time BASE risk stays frozen even when the actual fill gaps.
    entry = t['entry_price']
    require(math.isfinite(entry) and entry > 0, 'invalid actual entry')
    require(close(t['fees'], fee * t['quantity'] * (entry + t['exit_price'])), 'fee mismatch')
    pnl = t['quantity'] * (t['exit_price'] - entry) - t['fees']
    require(close(pnl, t['net_pnl']), 'PnL mismatch')
    require(close(label['net_r'], pnl / (t['quantity'] * risk)), 'net R mismatch')
    require(close(t['risk_amount'], t['quantity'] * risk), 'risk amount mismatch')
    return -entry * (1 + fee) / risk


def audit(config):
    require(config['scope'] == 'DEV_ONLY' and config['exposure'] == 'EXPOSED_RESEARCH', 'scope rejected')
    require((ROOT / config['dataset']).resolve() == DATA.resolve(), 'unauthorized dataset')
    report = json.loads((DATA / 'report.json').read_text())
    require(report['status'] == 'PASS' and report['exposure'] == 'EXPOSED_DEVELOPMENT', 'source audit rejected')
    # Hash all declared artifacts without parsing additional market/equity rows.
    for name, expected in report['artifacts'].items():
        require(Path(name).name == name, 'unsafe artifact path')
        require(sha(DATA / name) == expected, 'artifact hash mismatch: ' + name)
    tables = {}
    for name in ('features', 'labels', 'opportunities', 'partitions'):
        tables[name] = index_rows([json.loads(s) for s in (DATA / (name + '.jsonl')).read_text().splitlines()])
    ids = set(tables['labels'])
    require(all(set(t) == ids for t in tables.values()), 'join identity mismatch')
    require(len(ids) == 50, 'unexpected population')
    schema = json.loads((DATA / 'label_schema.json').read_text())
    require(schema['execution_policy'] == 'LEGACY_BAR_PROXY_BASE_10_5', 'wrong execution policy')
    selected, excluded, trade_ids = [], [], set()
    for sid, label in tables['labels'].items():
        f, o, p = (tables[k][sid] for k in ('features', 'opportunities', 'partitions'))
        require(o['run'] == 'dev_A_base_v4' and o['source_population'] == 'original_A_portfolio_path_candidates', 'non-A row')
        require(label['source'] == 'executed_virtual', 'wrong label source')
        require(f['snapshot_hash'] == o['snapshot_hash'] == label['feature_snapshot_hash'], 'snapshot mismatch')
        require(f['symbol'] == o['symbol'] == label['symbol'] and f['mode'] == o['mode'] == label['mode'], 'identity mismatch')
        require(f['signal_time'] == o['signal_time'] == label['signal_time'], 'signal time mismatch')
        require(f['available_at'] <= label['signal_time'] < report['authorized_cutoff'], 'feature availability')
        require(all(t <= label['signal_time'] for t in f['factor_as_of'].values()), 'future factor')
        for feature in config['features']:
            require(feature not in f['missing'] and math.isfinite(f['values'][feature]), 'missing selected feature')
        require(p['independent_oos'] is False, 'unexpected OOS identity')
        if label['status'] != 'mature':
            require(label['status'] == 'unavailable' and label['net_r'] is None and not p['population_eligible'], 'unfilled must not become zero')
            excluded.append(sid)
            continue
        require(p['population_eligible'] and label['information_end'] <= report['authorized_cutoff'], 'invalid maturity')
        require(label['dependence_group'] == p['dependency_group_id'], 'dependency identity mismatch')
        t = label['executed_trade']
        require(t['trade_id'] not in trade_ids and t['trade_id'] == o['original_trade_id'], 'duplicate/mismatched trade')
        require(t['exit_reason'] in ('stop', 'target', 'timeout', 'mode_invalidated'), 'non-strategy exit')
        trade_ids.add(t['trade_id'])
        lower = base_r(label, o)
        selected.append({'label': label, 'feature': f, 'partition': p, 'lower_r': lower})
    require(len(selected) == 27 and len(excluded) == 23, 'unexpected mature counts')
    groups = defaultdict(set)
    for r in selected:
        groups[r['label']['dependence_group']].add(r['partition']['partition'])
    crossing = {k: sorted(v) for k, v in groups.items() if len(v) > 1}
    overlap = []
    for i, a in enumerate(selected):
        for b in selected[i + 1:]:
            x, y = a['label'], b['label']
            if max(x['information_start'], y['information_start']) <= min(x['information_end'], y['information_end']):
                overlap.append([x['economic_signal_id'], y['economic_signal_id']])
    coverage = Counter(r['label']['symbol'] + ':' + r['label']['mode'] for r in selected)
    require(dict(coverage) == report['mature_by_symbol_mode'], 'coverage mismatch')
    return selected, {'source_report_sha256': sha(DATA / 'report.json'), 'verified_artifact_hashes': report['artifacts'],
        'mature': 27, 'excluded_unavailable': excluded, 'coverage': dict(coverage),
        'original_splits': dict(Counter(r['partition']['partition'] for r in selected)),
        'groups': {k: sorted(v) for k, v in groups.items()}, 'cross_split_groups': crossing,
        'overlapping_pairs': overlap, 'strict_received_time_evidence': False,
        'availability_limit': 'assumed-close historical replay only; not live receipt evidence',
        'B185_merged': False, 'heldout_market_rows_read': False}


def load_dev_artifact(path, *, purpose):
    require(purpose == 'DEV_ONLY', 'non-development model use refused')
    path = Path(path)
    meta = json.loads((path / 'artifact.json').read_text())
    require(meta['scope'] == 'DEV_ONLY' and meta['exposure'] == 'EXPOSED_RESEARCH'
            and meta['runtime_enabled'] is False, 'unsafe artifact')
    require(sha(path / 'posterior.nc') == meta['posterior_sha256'], 'posterior integrity failure')
    import arviz as az
    return az.from_netcdf(path / 'posterior.nc')


def diagnose_saved(output):
    """Exact diagnostics from immutable saved draws; never refits the model."""
    import arviz as az
    import numpy as np
    output = Path(output).resolve()
    require(output.parent == (ROOT / 'outputs/hybrid_regime_v1').resolve()
            and output.name.startswith('dev_fit_20260905_'), 'unauthorized output')
    trace = load_dev_artifact(output, purpose='DEV_ONLY')
    require(not (output / 'diagnostics_exact.json').exists()
            and not (output / 'parameter_summary_exact.csv').exists(), 'diagnostic outputs already exist')
    frozen = json.loads((output / 'preregistration.json').read_text())['config']
    names = ['alpha', 'beta', 'tau', 'sigma', 'nu', 'z', 'u_symbolmode']
    summary = az.summary(trace, var_names=names, round_to='none')
    summary.to_csv(output / 'parameter_summary_exact.csv')
    d = {'rhat_max': float(summary.r_hat.max()), 'ess_bulk_min': float(summary.ess_bulk.min()),
         'ess_tail_min': float(summary.ess_tail.min()), 'divergences': int(trace.sample_stats.diverging.sum()),
         'bfmi': az.bfmi(trace).tolist(), 'max_tree_depth': int(trace.sample_stats.tree_depth.max()),
         'method': 'unrounded ArviZ rank diagnostics, saved draws only; no refit',
         'diagnostic_source_sha256': sha(__file__),
         'posterior_sha256': sha(output / 'posterior.nc')}
    limits = frozen['diagnostics']
    d['sampler_pass'] = bool(np.isfinite(summary[['r_hat', 'ess_bulk', 'ess_tail']].to_numpy()).all()
        and d['rhat_max'] <= limits['rhat_max'] and d['ess_bulk_min'] >= limits['ess_bulk_min']
        and d['ess_tail_min'] >= limits['ess_tail_min'] and d['divergences'] <= limits['divergences_max']
        and min(d['bfmi']) >= limits['bfmi_min'])
    write_json(output / 'diagnostics_exact.json', d)
    print(json.dumps(d))
    return d


def fit(output, *, sampler_backend='pymc'):
    started = time.perf_counter()
    require(sampler_backend in ('pymc', 'numpyro'), 'unregistered numerical backend')
    backend_policy = json.loads((ROOT / 'config/hybrid_dev_backend_v1.json').read_text())
    require(backend_policy['fixed_model_config_sha256'] == sha(CONFIG), 'frozen statistical config changed')
    output = Path(output).resolve()
    require(output.parent == (ROOT / 'outputs/hybrid_regime_v1').resolve()
            and output.name.startswith('dev_fit_20260905_'), 'unauthorized output')
    output.mkdir(exist_ok=False)
    config = json.loads(CONFIG.read_text())
    write_json(output / 'preregistration.json', {'registered_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'config_sha256': sha(CONFIG), 'config': config, 'command': sys.argv,
        'module_sha256': sha(__file__), 'python': sys.version, 'executable':sys.executable,
        'sampler_backend':sampler_backend, 'runtime_prefix':sys.prefix,
        'numerical_backend_policy_sha256':sha(ROOT / 'config/hybrid_dev_backend_v1.json')})
    (output / 'training_source_snapshot.py').write_bytes(Path(__file__).read_bytes())
    (output / 'config_snapshot.json').write_bytes(CONFIG.read_bytes())
    try:
        rows, checks = audit(config)
        write_json(output / 'audit.json', checks)
        write_json(output / 'row_provenance.json', rows)
        import numpy as np
        import pymc as pm
        import arviz as az
        modes = ['RANGE', 'UP_TREND']
        cells = sorted({r['label']['symbol'] + ':' + r['label']['mode'] for r in rows})
        mi = np.array([modes.index(r['label']['mode']) for r in rows])
        ci = np.array([cells.index(r['label']['symbol'] + ':' + r['label']['mode']) for r in rows])
        cm = np.array([modes.index(c.split(':')[1]) for c in cells])
        raw = np.array([[r['feature']['values'][f] for f in config['features']] for r in rows])
        mean, scale = raw.mean(axis=0), raw.std(axis=0)
        require(bool(np.all(scale > 0)), 'constant feature')
        x, y = (raw - mean) / scale, np.array([r['label']['net_r'] for r in rows])
        write_json(output / 'transform.json', {'features': config['features'], 'mean': mean.tolist(), 'scale': scale.tolist(), 'fit_population': 'all27_EXPOSED_RESEARCH'})
        constants = np.array([y[mi == m].mean() for m in range(len(modes))])
        write_json(output / 'baseline.json', {'scope': 'DEV_ONLY', 'in_sample_only': True, 'mode_means': dict(zip(modes, constants.tolist())),
            'zero_rmse': float(np.sqrt(np.mean(y ** 2))), 'mode_mean_rmse': float(np.sqrt(np.mean((y - constants[mi]) ** 2)))})
        p = config['priors']
        with pm.Model(coords={'mode': modes, 'cell': cells, 'feature': config['features'], 'obs': np.arange(len(y))}) as model:
            alpha = pm.Normal('alpha', 0, p['alpha_sd'], dims='mode')
            beta = pm.Normal('beta', 0, p['beta_sd'], dims=('mode', 'feature'))
            tau = pm.HalfNormal('tau', p['tau_halfnormal_sd'], dims='mode')
            z = pm.Normal('z', 0, 1, dims='cell')
            u = pm.Deterministic('u_symbolmode', z * tau[cm], dims='cell')
            sigma = pm.HalfNormal('sigma', p['sigma_halfnormal_sd'], dims='mode')
            nu = pm.Deterministic('nu', 2 + pm.Exponential('nu_minus_two', p['nu_minus_two_exponential_rate']))
            mu = pm.Deterministic('mu', alpha[mi] + u[ci] + (beta[mi] * x).sum(axis=1), dims='obs')
            pm.StudentT('R', nu=nu, mu=mu, sigma=sigma[mi], observed=y, dims='obs')
            prior = pm.sample_prior_predictive(samples=config['prior_draws'], random_seed=config['prior_seed'])
            prior.to_netcdf(output / 'prior.nc')
            sampler_options = {'nuts_sampler':sampler_backend}
            if sampler_backend == 'numpyro':
                sampler_options['nuts_sampler_kwargs']={'chain_method':'sequential'}
            trace = pm.sample(draws=config['draws'], tune=config['tune'], chains=config['chains'], cores=1,
                random_seed=config['seed'], target_accept=config['target_accept'], progressbar=False,
                idata_kwargs={'log_likelihood': True}, **sampler_options)
            pm.sample_posterior_predictive(trace, random_seed=config['predictive_seed'], extend_inferencedata=True, progressbar=False)
        trace.to_netcdf(output / 'posterior.nc')
        summary = az.summary(trace, var_names=['alpha', 'beta', 'tau', 'sigma', 'nu', 'z', 'u_symbolmode'], round_to='none')
        summary.to_csv(output / 'parameter_summary.csv')
        limits = config['diagnostics']
        diagnostics = {'rhat_max': float(summary.r_hat.max()), 'ess_bulk_min': float(summary.ess_bulk.min()),
            'ess_tail_min': float(summary.ess_tail.min()), 'divergences': int(trace.sample_stats.diverging.sum()),
            'bfmi': az.bfmi(trace).tolist(), 'max_tree_depth': int(trace.sample_stats.tree_depth.max())}
        diagnostics['sampler_pass'] = bool(np.isfinite(summary[['r_hat','ess_bulk','ess_tail']].to_numpy()).all()
            and diagnostics['rhat_max'] <= limits['rhat_max'] and diagnostics['ess_bulk_min'] >= limits['ess_bulk_min']
            and diagnostics['ess_tail_min'] >= limits['ess_tail_min'] and diagnostics['divergences'] <= limits['divergences_max']
            and min(diagnostics['bfmi']) >= limits['bfmi_min'])
        write_json(output / 'diagnostics.json', diagnostics)
        lower = np.array([r['lower_r'] for r in rows])
        def predictive(values):
            values = np.asarray(values).reshape(-1, len(y))
            return {'quantiles_01_05_50_95_99': np.quantile(values, [.01, .05, .5, .95, .99]).tolist(),
                'impossible_loss_mass': float(np.mean(values < lower)),
                'replicate_mean_05_50_95': np.quantile(values.mean(axis=1), [.05, .5, .95]).tolist(),
                'replicate_sd_05_50_95': np.quantile(values.std(axis=1), [.05, .5, .95]).tolist(),
                'per_row_impossible_mass': np.mean(values < lower, axis=0).tolist()}
        pred = np.asarray(trace.posterior_predictive.R).reshape(-1, len(y))
        means = np.asarray(trace.posterior.mu).reshape(-1, len(y))
        pp = {'prior': predictive(prior.prior_predictive.R), 'posterior': predictive(pred),
            'observed_mean': float(y.mean()), 'observed_sd': float(y.std()), 'economic_lower_r': lower.tolist(),
            'support_derivation': 'nonnegative exit price: R >= -entry*(1+fee)/frozen_BASE_unit_risk; stop -1R is not hard economic support',
            'posterior_mean_in_sample_rmse': float(np.sqrt(np.mean((means.mean(axis=0) - y) ** 2))), 'strata': {}}
        for kind, labels in [('symbolmode', [cells[i] for i in ci]), ('exit', [r['label']['reason'] for r in rows])]:
            for value in sorted(set(labels)):
                mask = np.array([v == value for v in labels])
                pp['strata'][kind + ':' + value] = {'n': int(mask.sum()), 'observed_mean': float(y[mask].mean()),
                    'predictive_quantiles_05_50_95': np.quantile(pred[:, mask], [.05, .5, .95]).tolist()}
        write_json(output / 'predictive_checks.json', pp)
        write_json(output / 'development_predictions.json', [{'economic_signal_id': r['label']['economic_signal_id'],
            'p_win': float((pred[:, i] > 0).mean()), 'p_edge': float((means[:, i] > 0).mean()),
            'q05_mu': float(np.quantile(means[:, i], .05)), 'mu_pred': float(means[:, i].mean()),
            'predictive_quantiles_05_50_95': np.quantile(pred[:, i], [.05, .5, .95]).tolist(),
            'scope': 'EXPOSED_RESEARCH_NOT_CALIBRATED'} for i, r in enumerate(rows)])
        write_json(output / 'artifact.json', {'scope': 'DEV_ONLY', 'exposure': 'EXPOSED_RESEARCH', 'runtime_enabled': False,
            'sampler_backend':sampler_backend,
            'posterior_sha256': sha(output / 'posterior.nc'), 'config_sha256': sha(CONFIG),
            'model_status': 'TRAINED_DEV_ONLY', 'mean_inference_valid': False, 'predictive_probability_valid': False,
            'predictive_tail_valid': False, 'admission': 'ABSTAIN',
            'support_status': 'MODEL_MISSPECIFIED' if max(pp['posterior']['per_row_impossible_mass']) > limits['impossible_loss_mass_max'] else 'UNVALIDATED',
            'limits': ['27 portfolio-selected proxy labels', 'RANGE n=2; BTC trend n=1; absent cells unsupported',
                'all old train/validation/test labels exposed and used; no OOS or calibration',
                'conditional independence unverified; chain ESS is not market sample size',
                'historical assumed-close availability; no executable delayed-policy evidence'],
            'elapsed_seconds': time.perf_counter() - started})
        print(json.dumps({'output': str(output), 'elapsed_seconds': time.perf_counter() - started, 'diagnostics': diagnostics}))
    except Exception as exc:
        write_json(output / 'failure.json', {'type': type(exc).__name__, 'message': str(exc), 'elapsed_seconds': time.perf_counter() - started})
        raise
    finally:
        lock = subprocess.run([sys.executable, '-m', 'pip', 'freeze'], capture_output=True, text=True, check=True)
        (output / 'requirements.lock.txt').write_text(lock.stdout, encoding='utf-8')
