"""Compare the real bounded current-card readers on an existing TEST_ONLY store."""
from contextlib import closing
from datetime import timedelta
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sqlite3
import sys
from time import perf_counter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BASE = ROOT/'source/development/workspace'
sys.path.insert(0, str(BASE))
from kquant import options_one_minute as common
from kquant import options_opening_momentum as s0


def module(name, path):
    spec = spec_from_file_location(name, path)
    value = module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


path = ROOT/'source/evidence/new-machine-20261008/delivery7-method-short-20261016-v4/TEST_ONLY-research.sqlite3'
with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=.2)) as db:
    db.execute('PRAGMA query_only=ON')
    raw = db.execute('SELECT payload_json FROM evaluations WHERE policy_hash=? ORDER BY evaluated_at DESC LIMIT 1',
        (s0.load_policy()['policy_hash'],)).fetchone()[0]
event = json.loads(raw)
now = common.timestamp(event['evaluated_at']) + timedelta(seconds=1)
readers = [('before', module('kquant._d7_query_before', BASE/'kquant/options_opening_trend_store.py')),
    ('after', module('kquant._d7_query_after', HERE/'next-patches/kquant/options_opening_trend_store.py'))]
results = []
for iteration in range(5):
    for name, reader in readers:
        started = perf_counter()
        try:
            value = reader.current_cards(path=path, session=event['session'], scope_hash=event['scope_hash'],
                now=now, policy=s0.load_policy())
            result = dict(reader=name, iteration=iteration, seconds=perf_counter()-started,
                result_sha256=common.digest(value), total=value['evaluations_total'], error=None)
        except Exception as exc:
            result = dict(reader=name, iteration=iteration, seconds=perf_counter()-started,
                result_sha256=None, error=type(exc).__name__, message=str(exc)[:100])
        results.append(result)
output = dict(test_only=True, read_only=True, store=str(path), as_of=now.isoformat(), samples=results,
    all_successful_outputs_equal=len({row['result_sha256'] for row in results if row['error'] is None}) == 1,
    real_market_latency_claim=False, timeout_increased=False)
with (HERE/'current-query-profile.json').open('x', encoding='utf-8') as stream:
    json.dump(output, stream, indent=2)
print(json.dumps(output))
