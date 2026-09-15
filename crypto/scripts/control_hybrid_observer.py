"""Inspect or request stop of one isolated continuous observer; never kill PIDs."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def control(run, action):
    out = (ROOT / run).resolve()
    if not out.is_relative_to(ROOT / 'outputs/hybrid_regime_v1'):
        raise ValueError('Independent Hybrid observation required')
    manifest = out / 'preregistration.json'
    if manifest.stat().st_size > 65536:
        raise ValueError('Oversized observation manifest')
    contract = json.loads(manifest.read_text(encoding='utf-8'))
    if contract.get('scope') not in ('CONTINUOUS_RECEIVER_INTERVAL_RESEARCH', 'BOUNDED_PUBLIC_OBSERVATION_SERIES') or contract.get('execution_enabled') is not False:
        raise ValueError('Not an isolated continuous research observer')
    if action == 'stop':
        try:
            with (out / 'STOP').open('x', encoding='ascii') as marker:
                marker.write('Operator stop request; retain database and censored outcomes.\n')
        except FileExistsError:
            pass
        return {'stop_requested': True, 'process_termination_confirmed': False,
                'scope': str(out), 'original_services_modified': False}
    if action != 'status':
        raise ValueError('Unsupported action')
    path = next((out / name for name in ('manager_failure.json', 'report.json',
                 'status_publish_failure.json', 'status.json') if (out / name).exists()), out / 'status.json')
    if not path.exists():
        return {'state': 'NO_HEARTBEAT_YET', 'process_liveness_verified': False}
    if path.stat().st_size > 65536:
        raise ValueError('Oversized observation status')
    return {'recorded_status': json.loads(path.read_text(encoding='utf-8')),
            'process_liveness_verified': False, 'status_basis': 'Persisted heartbeat, not an OS process probe'}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['status', 'stop'])
    p.add_argument('--run', required=True)
    args = p.parse_args()
    print(json.dumps(control(args.run, args.action), indent=2))
