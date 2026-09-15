"""Descriptive localization of frozen sampler saturation; no refit or admission."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_delivery import load, sha, atomic_json


def scalar_series(trace, chain):
    """Keep mode-conditioned scales separate instead of flattening draws."""
    for name in ('acceptance_rate', 'energy', 'lp'):
        variable = trace.sample_stats[name]
        if variable.dims != ('chain', 'draw'):
            raise ValueError('Unexpected sample-stat dimensions')
        yield name, variable.isel(chain=chain).values
    for name in ('tau', 'sigma', 'nu'):
        variable = trace.posterior[name]
        if variable.dims == ('chain', 'draw'):
            yield name, variable.isel(chain=chain).values
        elif variable.dims == ('chain', 'draw', 'mode'):
            for index, mode in enumerate(variable.coords['mode'].values):
                yield f'{name}[{mode}]', variable.isel(chain=chain, mode=index).values
        else:
            raise ValueError('Unexpected posterior dimensions')


def run(output):
    import arviz as az
    import numpy as np
    output = (ROOT / output).resolve()
    if not output.is_relative_to(ROOT / 'outputs/hybrid_delivery'):
        raise ValueError('Independent output required')
    output.mkdir(parents=True, exist_ok=False)
    source = ROOT / 'outputs/hybrid_regime_v1/dev_fit_20260905_03'
    trace_path = source / 'posterior.nc'
    before = sha(trace_path)
    if load(source / 'artifact.json')['posterior_sha256'] != before:
        raise ValueError('Frozen posterior hash mismatch')
    atomic_json(output / 'preregistration.json', {
        'scope': 'POSTHOC_DEV_DIAGNOSTIC_NO_REFIT', 'posterior_sha256': before,
        'script_sha256': sha(Path(__file__)), 'step_cap': 1023,
        'windows_per_chain': 4, 'parameter_selection': ['tau', 'sigma', 'nu'],
        'mode_parameters': 'Separate named mode coordinates; never pool draws',
        'changes_to_sampler': False, 'gate_thresholds_defined': False})
    trace = az.from_netcdf(trace_path)
    stats = trace.sample_stats
    steps = np.asarray(stats.n_steps)
    if steps.shape != (4, 1500):
        raise ValueError('Unexpected frozen chain/draw dimensions')
    chains = []
    for chain in range(4):
        hit = steps[chain] >= 1023
        longest = current = 0
        for value in hit:
            current = current + 1 if value else 0
            longest = max(longest, current)
        comparisons = {}
        for name, values in scalar_series(trace, chain):
            if values.shape != (1500,) or not np.isfinite(values).all():
                raise ValueError('Scalar finite diagnostic required')
            comparisons[name] = {label: np.quantile(values[mask], [.1, .5, .9]).tolist() if mask.any() else None
                for label, mask in [('saturated', hit), ('not_saturated', ~hit)]}
        chains.append({'chain': chain, 'saturated_draws': int(hit.sum()),
            'longest_contiguous_run': longest,
            'quarter_counts': [int(x.sum()) for x in np.array_split(hit, 4)],
            'step_size_range': [float(np.min(stats.step_size[chain])), float(np.max(stats.step_size[chain]))],
            'bfmi': float(az.bfmi(trace)[chain]), 'conditional_quantiles': comparisons})
    if sha(trace_path) != before:
        raise ValueError('Frozen posterior changed')
    result = {'scope': 'DEV_ONLY_SAMPLER_LOCALIZATION', 'chains': chains,
        'posterior_sha256': before, 'refit': False, 'model_gate_pass': False,
        'causal_root_cause_proven': False,
        'limitation': 'Within-posterior conditional summaries are not market validation or independent tests; no thresholds selected',
        'mean_permission': 'UNVALIDATED', 'profit_probability_permission': 'UNVALIDATED',
        'tail_permission': 'UNVALIDATED', 'admission': 'ABSTAIN'}
    config = load(source / 'config_snapshot.json')
    artifact = load(source / 'artifact.json')
    registration = load(source / 'preregistration.json')
    if registration['config'] != config:
        raise ValueError('Frozen config disagrees with preregistration')
    result['adaptation_evidence'] = {
        'backend': artifact['sampler_backend'],
        'tune': config['tune'], 'target_accept': config['target_accept'],
        'seed': config['seed'], 'trace_groups': trace.groups(),
        'warmup_recorded': 'warmup_sample_stats' in trace.groups(),
        'config_sha256': sha(source / 'config_snapshot.json'),
        'training_source_sha256': sha(source / 'training_source_snapshot.py'),
        'interpretation': 'Retained step-size differences observed; adaptation trajectory unavailable without warmup records. No causal adaptation failure established.'}
    atomic_json(output / 'report.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = run(args.output)
    print([{k: c[k] for k in ('chain', 'saturated_draws', 'longest_contiguous_run', 'quarter_counts', 'bfmi', 'step_size_range')}
           for c in result['chains']])
