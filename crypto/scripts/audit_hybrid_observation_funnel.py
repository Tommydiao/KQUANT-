"""Read a consistent observer snapshot without taking ownership of its writer."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_delivery import atomic_json


def audit(database, output):
    database = Path(database).resolve()
    output = Path(output).resolve()
    if not database.is_relative_to(ROOT / 'outputs') or not output.is_relative_to(ROOT / 'outputs/hybrid_delivery'):
        raise ValueError('Independent observer evidence paths required')
    output.mkdir(parents=True, exist_ok=False)
    db = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=2)
    types, reasons, modes = Counter(), Counter(), Counter()
    decisions, signals, latest = 0, 0, {}
    identity = hashlib.sha256()
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        for key, payload, evidence in db.execute('SELECT id,payload,audit FROM observer_events ORDER BY id'):
            identity.update(json.dumps([key, payload, evidence], separators=(',', ':')).encode())
            event, entries = json.loads(payload), json.loads(evidence)
            types[event['type']] += 1
            for item in entries:
                if item.get('kind') != 'CLOSED_BAR_DECISION':
                    continue
                decisions += 1
                signals += item.get('signal') is not None
                symbol = item['symbol']
                modes[(symbol, item['mode'])] += 1
                for reason in item.get('reason_codes', []):
                    reasons[(symbol, reason)] += 1
                if symbol not in latest or item['signal_time'] > latest[symbol]['signal_time']:
                    latest[symbol] = {k: item.get(k) for k in
                        ('signal_time', 'available_at', 'mode', 'reason_codes', 'signal')}
        state_text = db.execute('SELECT state FROM observer_checkpoint WHERE id=1').fetchone()[0]
        state = json.loads(state_text)
        labels = db.execute('SELECT COUNT(*) FROM observer_labels').fetchone()[0]
    finally:
        db.close()
    result = {'scope': 'READ_ONLY_OBSERVER_FUNNEL_NOT_PERFORMANCE', 'database': str(database),
        'event_snapshot_hash': identity.hexdigest(),
        'checkpoint_hash': hashlib.sha256(state_text.encode()).hexdigest(),
        'events': dict(types), 'closed_decisions': decisions, 'technical_signals': signals,
        'opportunities': len(state['opportunities']), 'label_rows': labels,
        'mode_counts': [{'symbol': s, 'mode': m, 'count': n} for (s, m), n in sorted(modes.items())],
        'reason_counts': [{'symbol': s, 'reason': reason, 'count': n} for (s, reason), n in sorted(reasons.items())],
        'latest_decisions': latest, 'process_liveness_verified': False,
        'parameters_changed': False, 'execution_enabled': False}
    atomic_json(output / 'report.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.database, args.output), ensure_ascii=False))
