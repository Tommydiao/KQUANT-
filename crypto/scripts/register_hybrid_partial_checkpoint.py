"""Record bounded partial engineering evidence without promoting a task or gate."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_delivery import Delivery, atomic_json, load, sha


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--checkpoint', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    check = (ROOT / args.checkpoint).resolve()
    out = (ROOT / args.output).resolve()
    base = ROOT / 'outputs/hybrid_delivery'
    if not check.is_relative_to(base) or not out.is_relative_to(base):
        raise ValueError('Independent evidence directory required')
    if not load(check / 'checkpoint.json')['engineering_regression_pass']:
        raise ValueError('Current regression must pass')
    out.mkdir(parents=True, exist_ok=False)
    refs = [check / 'checkpoint.json', check / 'preregistration.json',
            ROOT / 'kquant_crypto/hybrid_mc_alternatives_v12.py',
            ROOT / 'outputs/hybrid_delivery/t21_stress_5000_20260906_01/report.json',
            ROOT / 'outputs/hybrid_delivery/t32_stream_contract_20260906/attempt_20260905T181729_092160Z/evidence.json',
            ROOT / 'kquant_crypto/hybrid_offline_stream_journal.py',
            ROOT / 'outputs/hybrid_delivery/t32_recovery_20260906_01/evidence.json']
    record = {'tasks': ['T21', 'T32'], 'scope': 'Future-cost benchmark, unselected inputs, offline stream decoding',
              'full_task_pass': False, 'G4': False, 'live_enabled': False,
              'evidence': {str(r.relative_to(ROOT)): sha(r) for r in refs}}
    path = out / 'partial.json'
    atomic_json(path, record)
    d = Delivery(ROOT)
    try:
        with d.db:
            d.event('PARTIAL_DELIVERY', {'path': str(path.relative_to(ROOT)), 'sha256': sha(path), 'tasks': ['T21', 'T32']})
        ownership = d.status()['file_ownership']
        if 'T21' in ownership:
            d.release('T21', 'parent:mc_stress_20260906')
        if 'T32' in ownership:
            d.release('T32', 'Pascal:01a07038-5ae8-7f90-9620-eecbc39961ab')
        d.project()
        atomic_json(out / 'state.json', d.status())
        atomic_json(out / 'readiness.json', d.prepare_live_approval())
    finally:
        d.close()


if __name__ == '__main__':
    main()
