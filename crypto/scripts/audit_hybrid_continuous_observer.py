"""Snapshot and audit one isolated observer without touching its writer."""
import argparse
from pathlib import Path
import sys
from datetime import datetime, UTC

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_delivery import atomic_json, load, sha
from kquant_crypto.hybrid_observer_run_audit import snapshot_database, audit_database
from kquant_crypto.hybrid_observation_window import registration_wait
from kquant_crypto.hybrid_clock import digest


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--run', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    run, out = (ROOT / args.run).resolve(), (ROOT / args.output).resolve()
    if not run.is_relative_to(ROOT / 'outputs/hybrid_regime_v1') or not out.is_relative_to(ROOT / 'outputs/hybrid_delivery'):
        raise ValueError('Independent observer and audit directories required')
    manifest = load(run / 'preregistration.json')
    if manifest.get('scope') != 'CONTINUOUS_RECEIVER_INTERVAL_RESEARCH' or manifest.get('execution_enabled') is not False:
        raise ValueError('Not a continuous research observer')
    out.mkdir(parents=True, exist_ok=False)
    atomic_json(out / 'preregistration.json', {'source_run': str(run.relative_to(ROOT)),
                'source_manifest_sha256': sha(run / 'preregistration.json'),
                'audit_source_sha256': sha(ROOT / 'kquant_crypto/hybrid_observer_run_audit.py'),
                'script_sha256': sha(Path(__file__)), 'created_at_local_utc': datetime.now(UTC).isoformat(),
                'snapshot_timeout_seconds': 20, 'source_write_access': False})
    snapshot = out / 'hybrid_observer_snapshot.sqlite3'
    try:
        window = manifest.get('observation_window')
        if window is not None:
            binding = load(run / 'window_registration.json')
            registration_wait(window, binding['persisted_monotonic'])
            if (binding['preregistration_sha256'] != sha(run / 'preregistration.json')
                    or binding['observation_window_hash'] != digest(window)
                    or manifest['observation_window_hash'] != digest(window)):
                raise ValueError('Frozen observation window mismatch')
        snapshot_database(run / 'hybrid_continuous.sqlite3', snapshot)
        report = audit_database(snapshot, observation_window=window)
        report['snapshot_sha256'] = sha(snapshot)
        report['source_requested_seconds'] = manifest['duration_seconds']
        atomic_json(out / 'report.json', report)
        print({k: report[k] for k in ('ledger_integrity_pass', 'event_counts', 'latest_opportunities', 'G3_passed')})
        return 0 if report['ledger_integrity_pass'] else 1
    except Exception as exc:
        atomic_json(out / 'failure.json', {'type': type(exc).__name__, 'audit_complete': False, 'G3_passed': False})
        raise


if __name__ == '__main__':
    sys.exit(main())
