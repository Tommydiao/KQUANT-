"""Credential-free delivery status and bounded receipt verification."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_delivery import Delivery


def main():
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['status', 'next', 'run-ready', 'verify', 'resume', 'pause-development', 'evidence-report', 'prepare-live-approval'])
    p.add_argument('--receipt')
    p.add_argument('--receipt-directory', default='outputs/hybrid_delivery/receipts')
    p.add_argument('--budget-seconds', type=float, default=60)
    args = p.parse_args()
    d = Delivery(ROOT)
    try:
        if args.command == 'verify':
            if not args.receipt:
                p.error('--receipt required')
            result = {'changed': d.record(args.receipt)}
        elif args.command in ('resume', 'pause-development'):
            d.pause(args.command == 'pause-development')
            result = d.status()
        elif args.command == 'run-ready':
            result = d.run_ready(args.receipt_directory, args.budget_seconds)
        elif args.command == 'prepare-live-approval':
            result = d.prepare_live_approval()
        else:
            result = d.status()
            if args.command == 'next':
                result = {'next_task': result['next_task'], 'ready': result['ready'], 'paused': result['paused']}
        d.project()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        d.close()


if __name__ == '__main__':
    main()
