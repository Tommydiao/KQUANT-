"""Run the original A portfolio on authorized DEV input, then common risk paths."""
import argparse
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.candidate_policy import load_policy, digest
from kquant_crypto.candidate_simulation import CandidatePortfolio
from kquant_crypto.strategy_dual_mode_v1 import Bar
from kquant_crypto.hybrid_delivery import atomic_json, Delivery, sha, load
from kquant_crypto.hybrid_mc_history_v12 import load_authorized, AUTHORIZED_END
from kquant_crypto.hybrid_mc_paths_v12 import SYMBOLS, generate_paths
from kquant_crypto.hybrid_mc_portfolio_v12 import evaluate_path


def run(output):
    out = (ROOT / output).resolve()
    if not out.is_relative_to(ROOT / 'outputs/hybrid_delivery'):
        raise ValueError('Independent evidence output required')
    out.mkdir(parents=True, exist_ok=False)
    sources = ['kquant_crypto/candidate_simulation.py', 'kquant_crypto/strategy_dual_mode_v1.py',
               'kquant_crypto/hybrid_mc_portfolio_v12.py', 'kquant_crypto/hybrid_mc_numerics_v12.py',
               'scripts/run_hybrid_mc_portfolio_dev.py']
    source_hashes = {p: sha(ROOT / p) for p in sources}
    for relative in sources:
        destination = out / 'source_snapshot' / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((ROOT / relative).read_bytes())
    atomic_json(out / 'preregistration.json', {'start': AUTHORIZED_END - 30 * 86400 - 300,
        'end': AUTHORIZED_END, 'paths': 32, 'horizon_bars': 72, 'seed': 20260906,
        'candidate': 'A', 'selection': 'fixed_existing_A_no_AB_comparison', 'scope': 'EXPOSED_DEV_ONLY',
        'source_hashes': source_hashes, 'live_enabled': False})
    started = time.monotonic()
    history, spec, audit = load_authorized(ROOT, start=AUTHORIZED_END - 30 * 86400 - 300, end=AUTHORIZED_END)
    # Reuse the original frozen exchange rule snapshot, not invented quantities.
    rules_file = ROOT / 'outputs/dual_regime_v1/exchange_rules.json'
    if not rules_file.exists():
        raise ValueError('Frozen exchange rule filename must be inspected before run')
    rules = load(rules_file)['rules']
    if digest(rules) != '4fc3b1badb1b338b19b9fa1c779c7a06697adf7d03afc5b5879bae1e12e25768':
        raise ValueError('Original frozen rule hash mismatch')
    p = CandidatePortfolio(load_policy(candidate='A'), rules)
    parts = {s: [] for s in SYMBOLS}
    high_watermark = p.value()
    for batch in history:
        t = batch['start']
        bars = {s: Bar(t, **{k: batch['bars'][s][k] for k in ('open', 'high', 'low', 'close', 'volume')}) for s in SYMBOLS}
        hourly = {}
        for s, b in bars.items():
            if t % 3600 == 0:
                parts[s] = []
            parts[s].append(b)
            if (t + 300) % 3600 == 0 and len(parts[s]) == 12:
                x = parts[s]
                hourly[s] = Bar(x[0].start, x[0].open, max(a.high for a in x), min(a.low for a in x), x[-1].close, sum(a.volume for a in x))
        p.on_closed_batch(bars, hourly, t + 300)
        high_watermark = max(high_watermark, p.value())
    state = p.snapshot()
    atomic_json(out / 'initial_state.json', state)
    atomic_json(out / 'historical_input_audit.json', audit)
    paths = generate_paths(history, p.marks, spec)
    reports = [evaluate_path(p.policy, rules, state, x['batches'], as_of=AUTHORIZED_END,
                            historical_high_watermark=high_watermark) for x in paths['path_bank']['paths']]
    atomic_json(out / 'risk_paths.json', reports)
    command = [sys.executable, '-m', 'pytest', '-q', 'tests/test_hybrid_mc_portfolio_v12.py',
               'tests/test_hybrid_mc_numerics_v12.py', 'tests/test_candidate_portfolio.py']
    test = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=180)
    (out / 'tests.log').write_bytes(test.stdout + test.stderr)
    report = {'scope': 'ACTUAL_EXPOSED_DEV_PORTFOLIO_PATHS', 'candidate': 'A',
              'initial_positions': len(p.positions), 'initial_pending': len(p.pending),
              'initial_equity': p.value(), 'historical_high_watermark': high_watermark,
              'paths': len(reports), 'path_bank_hash': paths['path_bank_hash'],
              'initial_state_unchanged': digest(state) == digest(p.snapshot()),
              'source_hashes_unchanged': all(sha(ROOT / f) == h for f, h in source_hashes.items()),
              'rules_sha256': sha(rules_file), 'tests_command': command, 'tests_exit_code': test.returncode,
              'elapsed_seconds': time.monotonic() - started, 'risk_paths_sha256': sha(out / 'risk_paths.json'),
              'G4_passed': False, 'sizing_enabled': False, 'live_enabled': False,
              'remaining': ['5000-path performance', 'New-proposal size alternatives and stress costs',
                            'Formal numerical admission policy and probability calibration'],
              'not_a_new_AB_selection_or_OOS_report': True}
    report['historical_exchange_filters'] = 'CURRENT_RULES_PROXY_NOT_PIT'
    atomic_json(out / 'report.json', report)
    d = Delivery(ROOT)
    try:
        with d.db:
            d.event('PARTIAL_DELIVERY', {'task': 'T21', 'path': str((out / 'report.json').relative_to(ROOT)),
                    'sha256': sha(out / 'report.json'), 'full_task_verified': False})
        d.project()
    finally:
        d.close()
    return test.returncode


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    sys.exit(run(args.output))
