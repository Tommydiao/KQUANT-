"""Locate frozen sampling failures without adapting or rerunning the sampler."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha, write_json
from kquant_crypto.hybrid_multifactor_artifact import inspect_artifact


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fit', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    fit, out = [(ROOT / value).resolve() for value in (args.fit, args.output)]
    if any(not p.is_relative_to(ROOT / 'outputs/hybrid_delivery') for p in (fit, out)):
        raise ValueError('Independent research paths required')
    meta = inspect_artifact(fit, purpose='DEV_ONLY')
    progress = json.loads((fit / 'progress.json').read_text())
    if meta['version'] != 'population_student_t_dev_v1' or progress['completed_chains'] != 4:
        raise ValueError('Complete population model required')
    import arviz as az
    import numpy as np
    trace = az.from_netcdf(fit / 'posterior.nc')
    if trace.posterior.sizes['chain'] != 4 or trace.posterior.sizes['draw'] != 1000:
        raise ValueError('Incomplete combined posterior')
    results = []
    for i in range(4):
        path = fit / f'chain_{i}.nc'
        if sha(path) != progress['chain_hashes'][str(i)]:
            raise ValueError('Chain changed after checkpoint')
        single = az.from_netcdf(path)
        for name in single.posterior.data_vars:
            np.testing.assert_array_equal(single.posterior[name].isel(chain=0),
                                          trace.posterior[name].isel(chain=i))
        stats = single.sample_stats
        hits = np.flatnonzero(np.asarray(stats.diverging).reshape(-1))
        details = []
        for draw in hits:
            parameters = {name: float(single.posterior[name].isel(chain=0, draw=int(draw)))
                          for name in ('alpha', 'tau', 'sigma', 'nu_minus_two')}
            details.append({'draw_index': int(draw), 'parameters': parameters,
                'note': 'Stored divergent draw is diagnostic evidence, not proof of a unique root cause'})
        result = {'chain': i, 'chain_hash': sha(path), 'divergences': len(hits),
                  'bfmi': float(az.bfmi(single)[0]), 'divergent_draws': details}
        for field in ('tree_depth', 'n_steps', 'step_size', 'acceptance_rate'):
            values = np.asarray(stats[field])
            result[field] = {'mean': float(values.mean()), 'max': float(values.max())}
        result['max_depth_hits'] = int(stats.reached_max_treedepth.sum())
        results.append(result)
        single.close()
    summary = az.summary(trace, var_names=['alpha', 'beta', 'tau', 'sigma', 'nu_minus_two', 'z'], round_to='none')
    registered = json.loads((fit / 'preregistration.json').read_text())['diagnostics']
    measured = {'rhat_max': float(summary.r_hat.max()), 'ess_bulk_min': float(summary.ess_bulk.min()),
                'ess_tail_min': float(summary.ess_tail.min()),
                'divergences': sum(r['divergences'] for r in results)}
    checks = {'rhat': measured['rhat_max'] <= registered['rhat_max'],
              'ess_bulk': measured['ess_bulk_min'] >= registered['ess_min'],
              'ess_tail': measured['ess_tail_min'] >= registered['ess_min'],
              'divergences': measured['divergences'] <= registered['divergences_max']}
    for name, value in measured.items():
        if not np.isclose(value, meta['diagnostics'][name], rtol=1e-10, atol=1e-10):
            raise ValueError('Saved diagnostics differ from recomputed posterior')
    out.mkdir(exist_ok=False)
    result = {'scope': 'DEV_ONLY_FROZEN_FAILURE_LOCALIZATION', 'chains': results,
        'measured': measured, 'registered_limits': registered, 'numerical_checks': checks,
        'numerical_gate': 'PASS' if all(checks.values()) else 'FAIL',
        'posterior_hash': meta['posterior_sha256'], 'source_code_hash': sha(Path(__file__)),
        'parameter_changes': False, 'refit': False, 'runtime_enabled': False,
        'performance': 'PERFORMANCE_UNPROVEN', 'probability_calibrated': False}
    write_json(out / 'report.json', result)
    trace.close()
    print(json.dumps(result))


if __name__ == '__main__':
    main()
