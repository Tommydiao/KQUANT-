"""Bounded stored-posterior geometry inspection; never refits or changes gates."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
import arviz as az

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha, write_json


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    args = p.parse_args()
    base = ROOT / 'outputs/hybrid_delivery'
    model = base / 'multifactor_population_fit_20260908_01'
    out = (ROOT / args.output).resolve()
    if not out.is_relative_to(base) or out.exists():
        raise ValueError('New isolated output required')
    meta = json.loads((model / 'artifact.json').read_text())
    if sha(model / 'posterior.nc') != meta['posterior_sha256']:
        raise ValueError('Posterior changed')
    trace = az.from_netcdf(model / 'posterior.nc')
    series = {}
    for name in ('alpha', 'sigma', 'tau', 'nu_minus_two'):
        series[name] = np.asarray(trace.posterior[name].transpose('chain', 'draw'))
    z = trace.posterior.z.transpose('chain', 'draw', 'group')
    for i, group in enumerate(z.coords['group'].values):
        series['z:' + str(group)] = np.asarray(z)[:, :, i]
    if any(not np.isfinite(a).all() for a in series.values()):
        raise ValueError('Nonfinite posterior')
    neighborhoods = []
    for chain, draw in np.argwhere(np.asarray(trace.sample_stats.diverging)):
        nearby = range(max(0, int(draw) - 5), min(trace.posterior.sizes['draw'], int(draw) + 6))
        neighborhoods.append({'chain': int(chain), 'draw': int(draw),
            'parameters': {name: {'at_draw': float(a[chain, draw]),
                'empirical_pooled_percentile': float(np.mean(a <= a[chain, draw])),
                'nearby_stored_draws': [{'draw': d, 'value': float(a[chain, d])} for d in nearby]}
                for name, a in series.items()}})
    correlations = {}
    tau = series['tau'].reshape(-1)
    for name, values in series.items():
        if name != 'tau':
            other = values.reshape(-1)
            correlations[name] = float(np.corrcoef(tau, other)[0, 1]) if np.std(other) > 0 and np.std(tau) > 0 else None
    result = {'scope': 'DEV_ONLY_STORED_POSTERIOR_DIAGNOSTIC',
        'posterior_hash': meta['posterior_sha256'], 'code_hash': sha(Path(__file__)),
        'divergence_neighborhoods': neighborhoods, 'pooled_tau_correlations': correlations,
        'refit': False, 'numerical_gate': 'FAIL' if neighborhoods else 'NOT_REASSESSED',
        'root_cause_proven': False, 'runtime_enabled': False,
        'limitations': ['Stored draw is not the full divergent leapfrog trajectory',
            'Pooled correlations are descriptive, not proof of a funnel',
            'No posterior draws removed; no tolerances or parameters changed']}
    out.mkdir(exist_ok=False)
    write_json(out / 'report.json', result)
    print(json.dumps({'divergences': len(neighborhoods), 'tau_correlations': correlations,
                      'report': str(out / 'report.json')}))


if __name__ == '__main__':
    main()
