"""Bounded read-only historical trace; reproduce validation, never enqueue replay."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import time

from kquant import options_minute_decisions as installed

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]


def connection(path):
    db = sqlite3.connect(Path(path).as_uri()+'?mode=ro', uri=True, timeout=.2)
    db.execute('PRAGMA query_only=ON')
    deadline = time.monotonic()+3
    db.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
    return db


def main():
    started = datetime.now(timezone.utc)
    roles = json.loads((ROOT/'runtime/config/new-epoch-store-paths.json').read_text(encoding='utf-8-sig'))['stores']
    result = {'started_at': started.isoformat(), 'session': '2026-10-21',
              'production_writes': 0, 'sdk_calls': 0, 'errors': []}
    with closing(connection(roles['opening_research'])) as db:
        rows = db.execute('''SELECT job_id,symbol,slot,state,reason,queued_at,deadline_at,payload_json
            FROM two_hour_jobs WHERE session=? AND symbol=? LIMIT 40''', ('2026-10-21', 'ASTS')).fetchall()
        result['tasks'] = [dict(zip(('job_id','symbol','slot','state','reason','queued_at','deadline_at','payload'),
                               (*row[:-1], json.loads(row[-1])))) for row in rows]
    with closing(connection(roles['minute'])) as db:
        rows = db.execute('''SELECT payload_json FROM one_minute_bars
            WHERE session=? AND symbol=? LIMIT 1000''', ('2026-10-21', 'ASTS')).fetchall()
    result['raw_sample_count'] = len(rows)
    patch = HERE.parent/'monday-signal-llm/recovery-null-time-followup/patches/kquant/options_minute_decisions.py'
    spec = importlib.util.spec_from_file_location('kquant._isolated_null_time_trace', patch)
    fixed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixed)
    result['installed_sha256'] = hashlib.sha256(Path(installed.__file__).read_bytes()).hexdigest()
    result['candidate_sha256'] = hashlib.sha256(patch.read_bytes()).hexdigest()
    result['reproductions'] = []
    for raw, in rows:
        value = json.loads(raw)
        native = value.get('sdk_evidence', {})
        if native.get('interface') != 'QuoteContext.set_on_candlestick' or native.get('request_started_at') is not None:
            continue
        if not native.get('clock_evidence'):
            continue
        record = {'raw_sha256': hashlib.sha256(raw.encode()).hexdigest(),
                  'available_at': value.get('available_at'), 'received_at': value.get('received_at'),
                  'interface': native.get('interface'), 'request_started_at': None,
                  'proof_scope': 'EMPTY_PROOF_VALIDATION_ONLY_NOT_SOURCE_ACCEPTANCE'}
        for label, module in (('installed', installed), ('candidate', fixed)):
            try:
                record[label] = {'accepted': module._local_candidate(value, {})}
            except Exception as exc:
                record[label] = {'exception_type': type(exc).__name__}
        result['reproductions'].append(record)
        if len(result['reproductions']) == 3:
            break
    result['conclusion'] = 'SAMPLE_VALIDATION_ONLY_NOT_FULL_WINDOW_CAUSAL_ATTRIBUTION'
    result['finished_at'] = datetime.now(timezone.utc).isoformat()
    output = HERE/('missing-evaluation-trace-'+started.strftime('%Y%m%dT%H%M%SZ')+'.json')
    with output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'evidence': str(output), 'tasks': len(result['tasks']),
                      'raw_sample_count': len(rows), 'reproductions': result['reproductions']}))


if __name__ == '__main__':
    main()
