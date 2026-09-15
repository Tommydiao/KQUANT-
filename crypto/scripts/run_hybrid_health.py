"""Local health-journal entrypoint. Missing observations stay UNKNOWN."""
import argparse
import json
from pathlib import Path
import sys
import time
import hashlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_health_journal import HealthJournal


def save_probe_evidence(path, result):
    path = (ROOT / path).resolve()
    if not path.is_relative_to(ROOT / 'outputs/hybrid_delivery'):
        raise ValueError('Independent evidence location required')
    path.parent.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / 'kquant_crypto' / ('hybrid_' + name + '.py')
               for name in ('health_contract', 'health_journal', 'local_health_probe', 'loopback_transport', 'model_health')]
    sources.append(Path(__file__))
    payload = {'scope': 'LOCAL_PROBE_NOT_TRADING_ATTESTATION', 'result': result,
               'source_hashes': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in sources}, 'live_enabled': False}
    with path.open('x', encoding='utf-8') as stream:
        json.dump(payload, stream, sort_keys=True, indent=2)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['record', 'status', 'probe'])
    p.add_argument('--directory', default='work/hybrid_delivery/health')
    p.add_argument('--observations')
    p.add_argument('--max-age', type=int, default=60)
    p.add_argument('--evidence')
    args = p.parse_args()
    directory = (ROOT / args.directory).resolve()
    if not directory.is_relative_to(ROOT / 'work/hybrid_delivery'):
        raise ValueError('Independent delivery journal required')
    j = HealthJournal(directory)
    try:
        if args.command == 'probe':
            from kquant_crypto.hybrid_local_health_probe import probe
            from kquant_crypto.hybrid_model_health import inspect_model_metadata
            result = probe()
            result['model_metadata'] = inspect_model_metadata(ROOT / 'outputs/hybrid_regime_v1/dev_fit_20260905_03/artifact.json')
            result['observations']['model'] = {'state':result['model_metadata']['state'], 'observed_at':result['observed_at']}
            result['journal'] = j.append(result.pop('observations'), now=result['observed_at'], max_age=args.max_age)
            if args.evidence:
                save_probe_evidence(args.evidence, result)
            print(json.dumps(result))
        elif args.command == 'record':
            values = {}
            if args.observations:
                with Path(args.observations).open('rb') as stream:
                    raw = stream.read(65537)
                if len(raw) > 65536:
                    raise ValueError('Observation input exceeds limit')
                values = json.loads(raw)
            print(json.dumps(j.append(values, now=int(time.time()), max_age=args.max_age)))
        else:
            row = j.db.execute('SELECT observed_at,report FROM health_samples ORDER BY id DESC LIMIT 1').fetchone()
            print(json.dumps({'last_recorded_local_time': row[0] if row else None,
                              'historical_report': json.loads(row[1]) if row else None,
                              'live_probe_performed': False, 'execution_authorized': False}))
    finally:
        j.close()


if __name__ == '__main__':
    main()
