"""Reuse actual assembly harness, with overlay hashes and spawned-child loading."""
from hashlib import sha256
from datetime import timedelta
import json
import os
from pathlib import Path
import sqlite3
import sys
from bootstrap import activate

DEV, BASE = activate()
os.environ['KQUANT_TEST_RESEARCH_OVERLAY'] = str(DEV)
os.environ['PYTHONPATH'] = str(DEV / 'tools') + os.pathsep + str(BASE)
sys.path.insert(0, str(BASE / 'scripts'))
import check_r58_p10_topology as harness

original_sources = harness.tested_sources
original_tree = harness.tested_tree
original_setup = harness.setup


def sources():
    result = {'base/' + key: value for key, value in original_sources().items()}
    for folder in ('kquant', 'tools'):
        result.update({'overlay/' + path.relative_to(DEV).as_posix(): sha256(path.read_bytes()).hexdigest()
            for path in (DEV / folder).rglob('*') if path.suffix in {'.py', '.cjs', '.mjs'}})
    return result


def tree(path):
    result = original_tree(path)
    if Path(path).resolve() == (BASE / 'web/src').resolve():
        result.update({'overlay/' + key: value for key, value in original_tree(DEV / 'web/src').items()})
    return result


harness.tested_sources = sources
harness.tested_tree = tree


def setup(cfg):
    original_setup(cfg)
    # Explicit synthetic transport versions with the new intraday contract.
    # Real Supervisor/Worker constructors, readers, resolver and journal stay intact.
    from kquant import options_one_minute as common
    minute = harness.minute_path(cfg)
    assert minute.is_relative_to(Path(cfg['out']))
    with sqlite3.connect(minute) as db:
        bars = [json.loads(row[0]) for row in db.execute('SELECT payload_json FROM one_minute_bars')]
    for bar in bars:
        bar['received_at'] = (common.timestamp(bar['received_at']) + timedelta(milliseconds=1)).isoformat()
        bar['sdk_evidence'] = {'interface': 'QuoteContext.candlesticks', 'adjustment': 'NoAdjust',
            'provider_symbol': bar['symbol'] + '.US', 'test_only': True}
        bar['test_only'] = True
    common.save_bars(bars, cfg['session'], minute)


harness.setup = setup

if __name__ == '__main__':
    raise SystemExit(harness.main())
