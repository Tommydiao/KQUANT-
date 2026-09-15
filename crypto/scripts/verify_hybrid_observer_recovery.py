"""Bounded replay of a read-only live snapshot into a disposable research ledger."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.candidate_policy import load_policy, digest
from kquant_crypto.hybrid_delivery import atomic_json, load, sha
from kquant_crypto.hybrid_observation import ObservationStore
from kquant_crypto.hybrid_observer_run_audit import snapshot_database


def run(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if not source.is_relative_to(ROOT / 'outputs') or not output.is_relative_to(ROOT / 'outputs/hybrid_delivery'):
        raise ValueError('Independent evidence directories required')
    output.mkdir(parents=True, exist_ok=False)
    snapshot = output / 'hybrid_snapshot.sqlite3'
    snapshot_database(source, snapshot)
    origin = sqlite3.connect(snapshot.as_uri() + '?mode=ro', uri=True)
    store = None
    started = time.monotonic()
    try:
        count = origin.execute('SELECT COUNT(*) FROM observer_events').fetchone()[0]
        if not 0 < count <= 20000:
            raise ValueError('Bounded nonempty snapshot required')
        policy = load_policy(candidate='A')
        rules = load(ROOT / 'outputs/dual_regime_v1/exchange_rules.json')['rules']
        destination = output / 'hybrid_replayed.sqlite3'
        store = ObservationStore(destination, policy, rules)
        if store.contract != origin.execute('SELECT hash FROM observer_contract WHERE id=1').fetchone()[0]:
            raise ValueError('Source contract mismatch; use pinned matching source')
        atomic_json(output / 'preregistration.json', {'source_snapshot_sha256': sha(snapshot),
            'contract': store.contract, 'events': count, 'max_seconds': 120,
            'source_write_access': False, 'execution_enabled': False})
        for index, (key, hashed, payload, audit) in enumerate(origin.execute(
                'SELECT id,hash,payload,audit FROM observer_events ORDER BY rowid')):
            if time.monotonic() - started > 120:
                raise TimeoutError('Recovery evidence budget exceeded')
            event = json.loads(payload)
            if digest(event) != hashed:
                raise ValueError('Source event integrity failure')
            result = store.process(key, event)
            if result['duplicate'] or result['audit'] != json.loads(audit):
                raise ValueError('Replayed decision differs from recorded audit')
            if index == count // 2:
                store.close()
                store = ObservationStore(destination, policy, rules)
        if not store.process(key, event)['duplicate']:
            raise ValueError('Replay duplicate not suppressed')
        checks = {}
        for table, columns, order in (
            ('observer_checkpoint', 'id,state', 'id'),
            ('observer_labels', 'signal_id,version,hash,payload', 'signal_id,version'),
            ('observer_events', 'id,hash,payload,audit', 'rowid'),
        ):
            query = f'SELECT {columns} FROM {table} ORDER BY {order}'
            checks[table] = origin.execute(query).fetchall() == store.db.execute(query).fetchall()
        if not all(checks.values()):
            raise ValueError('Recovery database mismatch')
        result = {'scope': 'OBSERVED_EVENT_RECOVERY_NOT_NEW_FORWARD_EVIDENCE',
            'events': count, 'checks': checks, 'restart_exercised': True,
            'duplicate_suppressed': True, 'elapsed_seconds': time.monotonic() - started,
            'G3_passed': False, 'execution_enabled': False}
        atomic_json(output / 'report.json', result)
        return result
    except Exception as exc:
        atomic_json(output / 'failure.json', {'type': type(exc).__name__, 'recovery_pass': False})
        raise
    finally:
        if store is not None:
            store.close()
        origin.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.output)))
