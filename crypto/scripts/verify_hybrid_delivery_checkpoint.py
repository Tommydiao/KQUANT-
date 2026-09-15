"""Capture a bounded local regression checkpoint without touching service writers."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_delivery import atomic_json, sha


def source_manifest(root):
    paths = set()
    for directory in ('kquant_crypto', 'tests', 'scripts', 'config', 'plan'):
        paths.update(p for p in (root / directory).rglob('*')
                     if p.is_file() and p.suffix.lower() in ('.py', '.ps1', '.cmd', '.bat', '.sh', '.json', '.toml', '.yml', '.yaml')
                     and '__pycache__' not in p.parts)
    for name in ('pyproject.toml', 'pytest.ini', 'requirements.txt', 'uv.lock'):
        path = root / name
        if path.is_file():
            paths.add(path)
    return {str(p.relative_to(root)): sha(p) for p in sorted(paths)}


def run(output):
    out = (ROOT / output).resolve()
    if not out.is_relative_to(ROOT / 'outputs/hybrid_delivery'):
        raise ValueError('Independent evidence output required')
    out.mkdir(parents=True, exist_ok=False)
    isolated = ROOT / 'work/hybrid_dev_fit_fast_env/Scripts/python.exe'
    commands = [
        ('crypto_regression', [sys.executable, '-m', 'pytest', '-q'], 900),
        ('isolated_math', [str(isolated), '-m', 'pytest', '-q',
                          'tests/test_hybrid_posterior_review.py',
                          'tests/test_hybrid_mc_paths_v12.py',
                          'tests/test_hybrid_mc_numerics_v12.py',
                          'tests/test_hybrid_mc_portfolio_v12.py',
                          'tests/test_hybrid_mc_alternatives_v12.py'], 180),
        ('diff_check', ['git', 'diff', '--check'], 60),
        ('baseline_audit', [sys.executable, '-m', 'kquant_crypto.hybrid_delivery_audit',
                            '--output', str((out / 'baseline').relative_to(ROOT))], 90),
    ]
    results = []
    before = source_manifest(ROOT)
    atomic_json(out / 'preregistration.json', {'commands': commands,
                'source_hashes': before, 'live_enabled': False,
                'scope': 'Local engineering regression; no model or trading gate'})
    for name, command, timeout in commands:
        start = time.monotonic()
        try:
            proc = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=timeout)
            output, code = proc.stdout + proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            output, code = (exc.stdout or b'') + (exc.stderr or b'') + b'\nTIMEOUT\n', 124
        (out / (name + '.log')).write_bytes(output)
        results.append({'name': name, 'command': command, 'cwd': str(ROOT),
                        'exit_code': code, 'elapsed_seconds': time.monotonic() - start,
                        'log_sha256': sha(out / (name + '.log'))})
        atomic_json(out / 'results.json', results)
        print(json.dumps(results[-1]), flush=True)
    after = source_manifest(ROOT)
    unchanged = before == after
    atomic_json(out / 'source_changes.json', {
        'added': sorted(after.keys() - before.keys()),
        'removed': sorted(before.keys() - after.keys()),
        'modified': sorted(key for key in before.keys() & after.keys() if before[key] != after[key]),
        'scope': 'Crypto Python and shell sources, tests, scripts, configuration, plans and dependency descriptors',
        'frontend_covered': False,
    })
    final = {'results': results, 'sources_unchanged_during_tests': unchanged,
             'engineering_regression_pass': unchanged and all(r['exit_code'] == 0 for r in results),
             'model_gate_pass': False, 'performance_gate_pass': False, 'live_enabled': False}
    atomic_json(out / 'checkpoint.json', final)
    return final


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    a = p.parse_args()
    result = run(a.output)
    sys.exit(0 if result['engineering_regression_pass'] else 1)
