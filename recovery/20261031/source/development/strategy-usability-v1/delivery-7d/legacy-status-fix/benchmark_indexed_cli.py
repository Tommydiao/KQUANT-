"""Production-shaped synthetic history through actual CLI; never opens active stores."""
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

HERE = Path(__file__).resolve().parent
OUT = HERE/'TEST_ONLY-volume'
if OUT.exists():
    raise SystemExit('EXISTING_FIXTURE_NOT_OVERWRITTEN')
OUT.mkdir()
for name in tuple(os.environ):
    if name.startswith('KQUANT_'):
        del os.environ[name]
os.environ.update(KQUANT_TEST_LEGACY_OVERLAY=str(HERE),
    PYTHONPATH=str(HERE/'tools')+os.pathsep+str(HERE.parents[4]/'source/development/workspace'))
from overlay import install
original, revised, worker = install()
from kquant.recovery_runtime_probe import MINUTE_STATUS_SCHEMA
from kquant.options_two_hour_data import universe

main, minute = OUT/'TEST_ONLY-main.sqlite3', OUT/'TEST_ONLY-minute.sqlite3'
with sqlite3.connect(main) as db:
    db.executescript('''CREATE TABLE stock_watchlist_groups(group_id,is_active);
        CREATE TABLE stock_watchlist_members(normalized_symbol,provider_symbol,identity_status,group_id,status);''')
    db.execute('INSERT INTO stock_watchlist_groups VALUES (?,1)', ('TEST_ONLY',))
    db.executemany('INSERT INTO stock_watchlist_members VALUES (?,?,?,?,?)',
        [(f'TEST_ONLY_{i:03}', f'TEST_ONLY_{i:03}.US' if i < 100 else None,
          'verified' if i < 100 else 'identity_unconfirmed', 'TEST_ONLY', 'active') for i in range(111)])
original.initialize(minute)
policy, scope = original.load_policy(), universe(main)['scope_hash']
as_of = datetime(2026, 10, 16, 21, tzinfo=UTC)
opening = as_of.replace(hour=13, minute=30)
with sqlite3.connect(minute) as db:
    for i in range(111):
        db.execute('INSERT INTO one_minute_prewarm VALUES (?,?,?,?,?,?)',
            ('2026-10-16', f'TEST_ONLY_{i:03}', 'PENDING' if i < 100 else 'IDENTITY_UNRESOLVED',
             'TEST_ONLY', as_of.isoformat(), '{}'))
    for i in range(75900):
        symbol = f'TEST_ONLY_{i % 100:03}'
        right = 'CALL' if i % 200 < 100 else 'PUT'
        end = opening+timedelta(minutes=i//200+1)
        payload = {'test_only': True, 'evaluation_id': str(i), 'symbol': symbol, 'right': right,
            'state': 'INCOMPLETE', 'factor_evidence': {}, 'policy_hash': policy['policy_hash'],
            'scope_hash': scope, 'deadline_at': (end+timedelta(seconds=30)).isoformat(),
            'diagnostic_padding': 'TEST_ONLY_'*160}
        db.execute('INSERT INTO one_minute_evaluations VALUES (?,?,?,?,?,?,?,?,?)',
            (str(i), str(i), '2026-10-16', symbol, right, end.isoformat(),
             'INCOMPLETE', json.dumps(payload), (end+timedelta(seconds=1)).isoformat()))


def business_digest():
    result = sha256()
    with sqlite3.connect(minute.as_uri()+'?mode=ro', uri=True) as db:
        for row in db.execute('SELECT * FROM one_minute_evaluations ORDER BY rowid'):
            result.update(json.dumps(row, separators=(',', ':')).encode())
    return result.hexdigest()


def attempt():
    started = time.perf_counter()
    try:
        result = worker.load_one_minute(main, minute_path=minute, now=as_of)
        return {'outcome': 'SUCCESS', 'whole_loader_seconds': time.perf_counter()-started,
            'transport': result['query_transport'], 'summary': result['summary'],
            'context_ms': result['history_context_ms']}
    except Exception as exc:
        return {'outcome': 'FAILED', 'whole_loader_seconds': time.perf_counter()-started,
            'diagnostic': getattr(exc, 'diagnostic', None), 'error_type': type(exc).__name__}


report = {'test_only': True, 'market_evidence': False, 'production_database_writes': 0,
    'observed_at': datetime.now(UTC).isoformat(), 'sdk_connections': 0, 'rows': 75900,
    'registered': 111, 'fixture': str(OUT), 'files': {p.relative_to(HERE/'patches').as_posix():
        sha256(p.read_bytes()).hexdigest() for p in (HERE/'patches').rglob('*.py')}}
report['before_business_sha256'] = business_digest()
report['before'] = attempt()
started = time.perf_counter()
with sqlite3.connect(minute) as db:
    db.execute(MINUTE_STATUS_SCHEMA[3])
    report['query_plan'] = db.execute('EXPLAIN QUERY PLAN SELECT rowid,symbol,right_name,bar_end,state,created_at '
        'FROM one_minute_evaluations WHERE session=?', ('2026-10-16',)).fetchall()
report['index_seconds'] = time.perf_counter()-started
report['after_business_sha256'] = business_digest()
assert report['before_business_sha256'] == report['after_business_sha256']
assert any('COVERING INDEX one_minute_status_metadata' in row[-1] for row in report['query_plan'])
report['after'] = [attempt() for _ in range(5)]
report['after_successes'] = sum(row['outcome'] == 'SUCCESS' for row in report['after'])
report['bytes'] = minute.stat().st_size
with (HERE/'indexed-cli-volume-result.json').open('x', encoding='utf-8') as stream:
    json.dump(report, stream, indent=2)
print(json.dumps({'before': report['before']['outcome'], 'after_successes': report['after_successes'],
    'after_attempts': len(report['after']), 'rows': report['rows'], 'query_plan': report['query_plan'],
    'seconds': [row['whole_loader_seconds'] for row in report['after']],
    'index_seconds': report['index_seconds'], 'business_unchanged': True, 'bytes': report['bytes']}))
