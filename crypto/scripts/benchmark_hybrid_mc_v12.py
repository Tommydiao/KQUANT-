"""Bounded 5000-path DEV benchmark with explicitly synthetic admitted exposure."""
import argparse
from copy import deepcopy
from dataclasses import replace
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.candidate_policy import load_policy
from kquant_crypto.candidate_simulation import CandidatePortfolio
from kquant_crypto.strategy_dual_mode_v1 import Bar
from kquant_crypto.hybrid_delivery import atomic_json, Delivery, sha, load
from kquant_crypto.hybrid_mc_history_v12 import AUTHORIZED_END, load_authorized
from kquant_crypto.hybrid_mc_paths_v12 import SYMBOLS, generate_paths, digest
from kquant_crypto.hybrid_mc_portfolio_v12 import evaluate_path
from kquant_crypto.hybrid_mc_alternatives_v12 import prepare_alternatives
from kquant_crypto.hybrid_mc_comparison_v12 import summarize_common_paths


def fixture(rules):
    p = CandidatePortfolio(load_policy(candidate='A'), rules)
    start = AUTHORIZED_END - 251 * 3600
    for h in range(251):
        price = 100 + h
        for i in range(12):
            t = start + h * 3600 + i * 300
            b = Bar(t, price, price + .1, price - .1, price, 1)
            hour = Bar(start + h * 3600, price, price + .1, price - .1, price, 12)
            p.on_closed_batch({s: b for s in SYMBOLS}, {s: hour for s in SYMBOLS} if i == 11 else {}, t + 300, False)
    b = Bar(AUTHORIZED_END, 350, 380, 340, 365, 1)
    p.on_closed_batch({s: b for s in SYMBOLS}, {}, AUTHORIZED_END + 300)
    if len(p.pending) != 2 or p.positions:
        raise ValueError('Synthetic fixture did not produce the frozen two-pending case')
    return p, {s: [b] for s in SYMBOLS}


def run(output, paths, alternatives=False):
    if paths not in (20, 5000):
        raise ValueError('Only preregistered smoke/full budgets')
    out = (ROOT / output).resolve()
    if not out.is_relative_to(ROOT / 'outputs/hybrid_delivery'):
        raise ValueError('Independent output required')
    out.mkdir(parents=True, exist_ok=False)
    sources = ['kquant_crypto/hybrid_mc_portfolio_v12.py', 'kquant_crypto/hybrid_mc_paths_v12.py',
               'kquant_crypto/hybrid_mc_numerics_v12.py', 'kquant_crypto/candidate_simulation.py',
               'scripts/benchmark_hybrid_mc_v12.py', 'kquant_crypto/hybrid_mc_alternatives_v12.py',
               'kquant_crypto/hybrid_mc_comparison_v12.py']
    hashes = {p: sha(ROOT / p) for p in sources}
    for p in sources:
        target = out / 'source_snapshot' / p
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / p).read_bytes())
    config = {'version': 'mc_bounded_stream_dev_v1', 'paths': paths, 'chunk_size': 50,
              'root_seed': 20260906, 'horizon_bars': 72, 'block_bars': 12,
              'costs': [1, 2], 'runtime_budget_seconds': 900,
              'exposure': 'SYNTHETIC_TWO_PENDING_NOT_CURRENT_ACCOUNT',
              'history': 'FIXED_EXPOSED_LAST_30_DAYS', 'source_hashes': hashes,
              'financial_permission': False}
    config.update(compare_alternatives=alternatives, family_alpha=.05, comparison_budget=4,
                  risk_events=['daily_loss'], probability_cost_scope='BASE_ONLY')
    atomic_json(out / 'preregistration.json', config)
    started = time.monotonic()
    history, original_spec, audit = load_authorized(ROOT, start=AUTHORIZED_END - 30 * 86400 - 300, end=AUTHORIZED_END)
    rules = load(ROOT / 'outputs/dual_regime_v1/exchange_rules.json')['rules']
    if digest(rules) != '4fc3b1badb1b338b19b9fa1c779c7a06697adf7d03afc5b5879bae1e12e25768':
        raise ValueError('Frozen rules changed')
    p, prefix = fixture(rules)
    state = deepcopy(p.snapshot())
    variants = [{'multiplier': 1, 'state': state}]
    if alternatives:
        # Independent synthetic scenario: retain BTC pending and re-propose ETH.
        # No running ledger or account state is edited.
        del state['pending']['ETHUSDT']
        prepared = prepare_alternatives(p.policy, rules, state, 'ETHUSDT', as_of=AUTHORIZED_END + 300)
        atomic_json(out / 'alternative_inputs.json', prepared)
        variants = prepared['alternatives']
    atomic_json(out / 'synthetic_initial_state.json', state)
    atomic_json(out / 'history_audit.json', audit)
    completed = 0
    aggregate_keys = [str(c) if not alternatives else f"{v['multiplier']}:{c}" for v in variants for c in (1, 2)]
    aggregates = {key: {'daily_loss_paths': 0, 'net_terminal_change_sum': 0.0} for key in aggregate_keys}
    chain = hashlib.sha256()
    comparisons = []
    with gzip.open(out / 'paths.jsonl.gz', 'wt', encoding='utf-8') as stream:
        for offset in range(0, paths, 50):
            if time.monotonic() - started >= 900:
                break
            count = min(50, paths - offset)
            seed = int(hashlib.sha256(f"mc_bounded_stream_dev_v1:20260906:{offset // 50}".encode()).hexdigest(), 16)
            spec = replace(original_spec, as_of=AUTHORIZED_END + 300, paths=count, seed=seed,
                           max_generated_symbol_bars=count * 72 * 3)
            bank = generate_paths(history, p.marks, spec)
            for entry in bank['path_bank']['paths']:
                row = {'path_id': completed, 'path_hash': digest(entry), 'costs': {}}
                for variant in variants:
                  for cost in (1, 2):
                    result = evaluate_path(p.policy, rules, variant['state'], entry['batches'], as_of=spec.as_of,
                        historical_high_watermark=10000, hour_prefix=prefix, future_cost_multiplier=cost,
                        include_terminal_state=False)
                    key = str(cost) if not alternatives else f"{variant['multiplier']}:{cost}"
                    aggregates[key]['daily_loss_paths'] += int(result['risk']['daily_loss_line_breached'])
                    aggregates[key]['net_terminal_change_sum'] += result['risk']['terminal_net_change']
                    row['costs'][key] = {k: result[k] for k in ('risk', 'curve', 'trades', 'remaining_positions', 'remaining_pending')}
                    if alternatives and cost == 1:
                        comparisons.append({'path_id': completed, 'alternative': variant['multiplier'],
                                            'events': {'daily_loss': result['risk']['daily_loss_line_breached']}})
                line = json.dumps(row, sort_keys=True, allow_nan=False)
                stream.write(line + '\n')
                chain.update(line.encode())
                completed += 1
            stream.flush()
            atomic_json(out / 'progress.json', {'completed': completed, 'requested': paths,
                        'elapsed_seconds': time.monotonic() - started, 'scope': config['exposure']})
    report = {'completed': completed, 'requested': paths, 'elapsed_seconds': time.monotonic() - started,
              'status': 'COMPLETED_BENCHMARK' if completed == paths else 'BUDGET_EXHAUSTED_PARTIAL',
              'record_hash': chain.hexdigest(), 'compressed_sha256': sha(out / 'paths.jsonl.gz'),
              'aggregates': aggregates, 'scope': config['exposure'],
              'market_probability_or_performance_pass': False, 'G4_passed': False,
              'source_unchanged': all(sha(ROOT / k) == h for k, h in hashes.items()),
              'limitations': ['Synthetic initial exposure, not account holdings', 'OHLC and current-rule proxy',
                              'No admission or market calibration', 'Stream seeds are a new explicit engineering version']}
    atomic_json(out / 'report.json', report)
    if alternatives and completed == paths:
        atomic_json(out / 'comparison.json', summarize_common_paths(comparisons, path_ids=list(range(paths)),
                    alternatives=(0,.25,.5,1), event_names=['daily_loss'], family_alpha=.05, comparison_budget=4))
    d = Delivery(ROOT)
    try:
        with d.db:
            d.event('PARTIAL_DELIVERY', {'task': 'T21', 'path': str((out / 'report.json').relative_to(ROOT)),
                                      'sha256': sha(out / 'report.json'), 'full_task_verified': False})
        d.project()
    finally:
        d.close()
    return 0 if completed == paths else 2


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    p.add_argument('--paths', type=int, choices=(20, 5000), required=True)
    p.add_argument('--alternatives', action='store_true')
    args = p.parse_args()
    sys.exit(run(args.output, args.paths, args.alternatives))
