"""Use the existing actual topology with isolated ports and current small delta."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
parser = argparse.ArgumentParser()
parser.add_argument('--name', required=True)
parser.add_argument('--hour', action='store_true')
parser.add_argument('--projection', type=Path)
args = parser.parse_args()
if not args.name.replace('-', '').isalnum():
    raise ValueError('INVALID_RUN_NAME')
out = ROOT/'source/evidence/new-machine-20261008'/args.name
command = [sys.executable, str(HERE/'tools/run_assembly.py'), '--out', str(out),
    '--dist', str(HERE/'build/unified'),
    '--watch', str(ROOT/'source/evidence/new-machine-20261008/delivery7-method-hour-d4f4aad4-20261017/TEST_ONLY-scope.json'),
    '--node', r'C:\Program Files\nodejs\node.exe',
    '--playwright-module', r'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\playwright\index.js',
    '--browser-executable', r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    '--evidence-root', str(ROOT/'source/evidence'),
    '--seconds', '3600' if args.hour else '120', '--checkpoint-interval', '300' if args.hour else '15',
    '--actual-assembly', '--observation-safe-hour', '--test-only-epoch-boundary',
    '--profile',
    '--backend-port', '8193', '--gateway-port', '8194', '--session', '2026-10-19']
if args.hour:
    command.append('--require-hour')
env = dict(os.environ)
if args.projection:
    env['KQUANT_TEST_FROZEN_PROJECTION'] = str(args.projection.resolve())
raise SystemExit(subprocess.call(command, env=env))
