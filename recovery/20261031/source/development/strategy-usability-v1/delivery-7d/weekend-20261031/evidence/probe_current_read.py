"""Reproduce one current-card read against a declared TEST_ONLY artifact."""
import argparse
from contextlib import contextmanager, closing
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import sqlite3
from time import perf_counter
import traceback

HERE = Path(__file__).resolve().parent
WEEKEND = HERE.parent
FIRST = WEEKEND.parent / 'opening-first-hour'
ROOT = WEEKEND.parents[4]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run')
    parser.add_argument('--at', required=True)
    parser.add_argument('--name', required=True)
    args = parser.parse_args()
    root = (ROOT / 'source/evidence/new-machine-20261008' / args.run).resolve()
    assert root.is_relative_to(ROOT / 'source/evidence') and (root / 'TEST_ONLY.json').is_file()
    assert args.name.replace('-', '').isalnum()
    role = root / 'TEST_ONLY-role-map.json'
    os.environ.update(KQUANT_TEST_WEEKEND_OVERLAY=str(WEEKEND),
        KQUANT_RUNTIME_DATA_ROOT=str(root), KQUANT_RUNTIME_PATH_BINDING=str(role),
        KQUANT_RUNTIME_PATH_BINDING_SHA256=sha256(role.read_bytes()).hexdigest(),
        KQUANT_TEST_FROZEN_PROJECTION=str(WEEKEND.parent / 'monday-signal-llm/release/local-candidate-7896a20b9c18c711/deployment-projection.json'))
    sys.path.insert(0, str(FIRST / 'assembly'))
    from bootstrap import activate
    activate()
    from first_hour import load_policy
    from kquant.options_opening_trend_store import current_cards
    from kquant import bounded_sqlite
    original_read = bounded_sqlite.read_connection
    statements = []

    @contextmanager
    def observed_read(*a, **kw):
        with original_read(*a, **kw) as db:
            db.set_trace_callback(statements.append)
            yield db

    bounded_sqlite.read_connection = observed_read
    scope = json.loads((root / 'TEST_ONLY-scope.json').read_text())
    started = perf_counter()
    result = dict(test_only=True, production_writes=0, run=args.run, at=args.at)
    try:
        value = current_cards(path=root / 'TEST_ONLY-research.sqlite3', session=args.at[:10],
            scope_hash=scope['scope_hash'], now=datetime.fromisoformat(args.at), policy=load_policy())
        result.update(state='RETURNED', total=value.get('evaluations_total'),
            displayed=len(value.get('evaluations', [])), diagnostics=value.get('current_projection'))
    except Exception as exc:
        result.update(state='FAILED', error_type=type(exc).__name__, error=str(exc),
                      traceback=traceback.format_exc(limit=8))
    result['seconds'] = perf_counter() - started
    bounded_sqlite.read_connection = original_read
    selected = next((sql for sql in statements if 'SELECT e.rowid,e.symbol' in sql), None)
    if selected:
        with closing(sqlite3.connect((root/'TEST_ONLY-research.sqlite3').as_uri()+'?mode=ro', uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            result['selection_query_plan'] = db.execute('EXPLAIN QUERY PLAN '+selected).fetchall()
        result['selection_sql_sha256'] = sha256(selected.encode()).hexdigest()
    result['source_sha256'] = sha256((FIRST / 'first_hour_store.py').read_bytes()).hexdigest()
    target = HERE / (args.name + '.json')
    target.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
