"""Record local T34/T40 contract tests without asserting production readiness."""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_delivery import Delivery, atomic_json, sha


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    out = (ROOT / args.output).resolve()
    if not out.is_relative_to(ROOT / 'outputs/hybrid_delivery'):
        raise ValueError('Independent evidence directory required')
    out.mkdir(parents=True, exist_ok=False)
    names = ['health_contract', 'reference_price_audit', 'exchange_rule_audit',
             'order_count_audit', 'rule_archive', 'rule_cache_v12',
             'health_journal', 'local_health_probe', 'loopback_transport']
    paths = [ROOT / f'kquant_crypto/hybrid_{name}.py' for name in names]
    paths += [ROOT / f'tests/test_hybrid_{name}.py' for name in names]
    paths += [Path(__file__), ROOT / 'scripts/run_hybrid_health.py',
              ROOT / 'tests/test_hybrid_health_evidence.py']
    before = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    command = [sys.executable, '-m', 'pytest', '-q'] + [f'tests/test_hybrid_{n}.py' for n in names]
    command.append('tests/test_hybrid_health_evidence.py')
    started = time.monotonic()
    with (out / 'tests.log').open('w', encoding='utf-8') as log:
        try:
            exit_code = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=120).returncode
        except subprocess.TimeoutExpired:
            log.write('\nBOUNDED_TEST_TIMEOUT\n')
            exit_code = 124
    after = {str(p.relative_to(ROOT)): sha(p) for p in paths}
    record = {'tasks': ['T34', 'T40'], 'scope': 'LOCAL_INPUT_CONTRACT_TESTS_ONLY',
              'command': command, 'exit_code': exit_code,
              'elapsed_seconds': time.monotonic()-started,
              'source_hashes': before, 'source_unchanged': before == after,
              'full_task_pass': False, 'account_verified': False,
              'external_notification_sent': False, 'live_enabled': False,
              'test_log_sha256': sha(out / 'tests.log')}
    atomic_json(out / 'evidence.json', record)
    d = Delivery(ROOT)
    try:
        with d.db:
            d.event('PARTIAL_DELIVERY', {'tasks': record['tasks'],
                    'path': str((out / 'evidence.json').relative_to(ROOT)),
                    'sha256': sha(out / 'evidence.json')})
        d.project()
    finally:
        d.close()
    return 0 if exit_code == 0 and before == after else 1


if __name__ == '__main__':
    raise SystemExit(main())
