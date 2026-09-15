"""Bounded T21 numerical evidence; never a completed portfolio-risk gate."""
import argparse
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_delivery import Delivery, atomic_json, sha


def run(output):
    out = (ROOT / output).resolve()
    if not out.is_relative_to(ROOT / 'outputs/hybrid_delivery'):
        raise ValueError('Independent output required')
    out.mkdir(parents=True, exist_ok=False)
    sources = ['kquant_crypto/hybrid_mc_numerics_v12.py', 'tests/test_hybrid_mc_numerics_v12.py']
    hashes = {p: sha(ROOT / p) for p in sources}
    atomic_json(out / 'preregistration.json', {'source_hashes': hashes,
                'scope': 'NUMERICAL_ENGINEERING_ONLY', 'family_alpha_test': .05,
                'comparison_budgets_tested': [6, 12], 'production_threshold_approved': False})
    results = []
    for name, python, tests in [
        ('isolated', str(ROOT / 'work/hybrid_dev_fit_fast_env/Scripts/python.exe'),
         ['tests/test_hybrid_mc_numerics_v12.py', 'tests/test_hybrid_mc_paths_v12.py']),
        ('shared', sys.executable,
         ['tests/test_hybrid_mc_numerics_v12.py', 'tests/test_candidate_portfolio.py', 'tests/test_hybrid_delivery.py']),
    ]:
        command = [python, '-m', 'pytest', '-q', *tests]
        started = time.monotonic()
        p = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=180)
        (out / (name + '.log')).write_bytes(p.stdout + p.stderr)
        results.append({'command': command, 'exit_code': p.returncode,
                        'elapsed_seconds': time.monotonic() - started,
                        'log_sha256': sha(out / (name + '.log'))})
        atomic_json(out / 'tests.json', results)
    unchanged = all(sha(ROOT / p) == h for p, h in hashes.items())
    report = {'scope': 'T21_PARTIAL_NUMERICS', 'source_hashes': hashes,
              'tests_pass': unchanged and all(r['exit_code'] == 0 for r in results),
              'G4_passed': False, 'sizing_enabled': False, 'live_enabled': False,
              'prior_attempt': {'evidence_kind': 'observed_tool_exit_not_raw_log',
                                'exit_code': 1, 'reason': 'Shared Python lacks scipy; isolated environment reused without installation'},
              'remaining': ['Original portfolio snapshot restoration and existing pending risk along common paths',
                            '6h 5000-path cost/stress/current-portfolio valuation and performance',
                            'Frozen numerical acceptance and calibrated risk interpretation'],
              'integration_hazard': 'allow_entries=False on CandidatePortfolio cancels existing pending; must suppress only future proposals',
              'reference': 'https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.beta.html'}
    atomic_json(out / 'report.json', report)
    d = Delivery(ROOT)
    try:
        with d.db:
            d.event('PARTIAL_DELIVERY', {'task': 'T21', 'path': str((out / 'report.json').relative_to(ROOT)),
                                      'sha256': sha(out / 'report.json'), 'full_task_verified': False})
        d.project()
    finally:
        d.close()
    return report['tests_pass']


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    args = p.parse_args()
    sys.exit(0 if run(args.output) else 1)
