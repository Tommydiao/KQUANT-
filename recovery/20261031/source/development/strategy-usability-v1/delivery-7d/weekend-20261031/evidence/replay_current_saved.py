"""Replay the saved real BTDR input; no provider call or current opportunity."""
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
WEEKEND = HERE.parent
FIRST = WEEKEND.parent / 'opening-first-hour'
os.environ['KQUANT_TEST_WEEKEND_OVERLAY'] = str(WEEKEND)
os.environ['KQUANT_TEST_FROZEN_PROJECTION'] = str(WEEKEND.parent / 'monday-signal-llm/release/local-candidate-7896a20b9c18c711/deployment-projection.json')
sys.path.insert(0, str(FIRST / 'assembly'))
from bootstrap import activate
activate()
import first_hour

source = WEEKEND.parent / 'monday-signal-llm/evidence/real-btdr-input.json'
raw = source.read_bytes()
saved = json.loads(raw)
rows = first_hour.evaluate_comparison_pair(**saved['arguments'])
flat = [v for row in rows for v in (row, row['strategy_comparison']['s1'])]
value = dict(schema='REAL_SAVED_INPUT_CURRENT_PAIR_REPLAY_V1',
    captured_at=datetime.now(timezone.utc).isoformat(), natural_signal=False,
    current_opportunity=False, sdk_requests=0, paid_calls=0, production_writes=0,
    source=str(source), source_sha256=sha256(raw).hexdigest(),
    math_source_sha256=sha256((FIRST/'first_hour.py').read_bytes()).hexdigest(),
    results=flat, contract_selection='NOT_EXECUTED_NO_HISTORICAL_QUOTE',
    live_market_acceptance=False)
target = HERE / ('saved-real-current-pair-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
with target.open('x', encoding='utf-8') as stream:
    json.dump(value, stream, indent=2)
print(json.dumps(dict(path=str(target), results=[dict(variant=r.get('variant'),
    symbol=r['symbol'], right=r['right'], state=r['state'], reasons=r.get('reasons')) for r in flat])))
