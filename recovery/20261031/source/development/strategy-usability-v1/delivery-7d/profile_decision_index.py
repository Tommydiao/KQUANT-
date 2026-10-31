"""Measure a bounded canonical lookup on isolated data, never production stores."""
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

HERE = Path(__file__).parent
QUERY = """SELECT payload_json FROM two_hour_jobs WHERE session=? AND symbol=?
    AND queued_at<=? AND json_extract(payload_json,'$.kind')=? ORDER BY queued_at LIMIT 501"""
ARGS = ('2026-10-19', 'TEST_ONLY_099', '2026-10-19T14:00:00+00:00', 'CANONICAL_MINUTE_DECISION_V1')


def measure(db):
    plan = [list(row) for row in db.execute('EXPLAIN QUERY PLAN '+QUERY, ARGS)]
    samples = []
    result_hashes = []
    for number in range(100):
        began = perf_counter()
        rows = db.execute(QUERY, (ARGS[0], f'TEST_ONLY_{number:03}', *ARGS[2:])).fetchall()
        samples.append(perf_counter()-began)
        result_hashes.append(sha256(json.dumps(rows, separators=(',', ':')).encode()).hexdigest())
    return dict(plan=plan, seconds=samples, p95=sorted(samples)[94], total=sum(samples),
        result_hashes=result_hashes)


def main():
    sys.path.insert(0, str(HERE/'tools'))
    from bootstrap import activate
    activate(verify=True)
    from kquant import options_opening_momentum_journal as journal
    destination = HERE/'canonical-index-profile.json'
    if destination.exists():
        raise ValueError('PROFILE_ALREADY_RECORDED')
    with TemporaryDirectory(prefix='KQUANT-TEST_ONLY-index-') as temporary:
        path = Path(temporary)/'TEST_ONLY.sqlite3'
        journal.initialize(path)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('DROP INDEX IF EXISTS trend_input_source')
            rows = []
            for symbol in range(100):
                for minute in range(30):
                    kind = ARGS[-1] if minute < 25 else 'OPENING_MOMENTUM_CALCULATION'
                    payload = json.dumps(dict(kind=kind, test_only=True, padding='x'*12000))
                    rows.append((f'{symbol}:{minute}', ARGS[0], f'TEST_ONLY_{symbol:03}', str(minute),
                        '2026-10-19T13:35:00+00:00', ARGS[2], payload))
            db.executemany("INSERT INTO two_hour_jobs VALUES (?,?,?,?,?,?,'COMPLETED',NULL,NULL,0,NULL,NULL,?)", rows)
        with closing(sqlite3.connect(path)) as db:
            before = measure(db)
            began = perf_counter()
            db.execute('CREATE INDEX trend_input_source ON two_hour_jobs(session,symbol,queued_at)')
            create_seconds = perf_counter()-began
            after = measure(db)
        assert before['result_hashes'] == after['result_hashes']
        output = dict(test_only=True, source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
            rows=3000, symbol_queries=100, index_creation_seconds=create_seconds,
            before=before, after=after, production_writes=0, market_latency_claim=False)
        with destination.open('x', encoding='utf-8') as stream:
            json.dump(output, stream, indent=2)
    print(json.dumps({k: output[k] for k in ('rows', 'index_creation_seconds')}))
    print(json.dumps({name: {key: output[name][key] for key in ('plan','p95','total')}
        for name in ('before','after')}))


if __name__ == '__main__':
    main()
