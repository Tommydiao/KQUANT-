"""Bounded real SQLite/function benchmark, synthetic bars, never production stores."""
import argparse
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE/'tools'))
from bootstrap import activate
activate(verify=True)
from kquant import options_minute_decisions as decisions
from kquant import options_opening_momentum_journal as journal
from kquant import options_one_minute as common
from test_method_binding import synthetic_inputs, proof, PATCH


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', choices=('before', 'after'), required=True)
    args = parser.parse_args()
    destination = HERE/('canonical-profile-'+args.label+'.json')
    if destination.exists():
        raise ValueError('PROFILE_ALREADY_RECORDED')
    fixture = synthetic_inputs()
    now = fixture['opening'] + timedelta(minutes=25, seconds=1)
    first, steady, connections = [], [], []
    native_connect = sqlite3.connect
    count = 0

    def traced_connect(*args, **kwargs):
        nonlocal count
        count += 1
        return native_connect(*args, **kwargs)

    with TemporaryDirectory(prefix='KQUANT-TEST_ONLY-canonical-') as temporary:
        path = Path(temporary)/'TEST_ONLY.sqlite3'
        journal.initialize(path)
        sqlite3.connect = traced_connect
        try:
            for number in range(20):
                symbol = f'TEST_ONLY_{number}'
                bars = []
                for minute in range(25):
                    row = deepcopy(fixture['bars'][2])
                    start = fixture['opening'] + timedelta(minutes=minute)
                    end = start + timedelta(minutes=1)
                    request = end + timedelta(milliseconds=100)
                    row.update(symbol=symbol, open_at=start.isoformat(), available_at=end.isoformat(),
                        request_started_at=request.isoformat(), received_at=(end+timedelta(milliseconds=300)).isoformat())
                    row['sdk_evidence'].update(provider_symbol=symbol+'.US', request_started_at=request.isoformat())
                    row['sdk_evidence']['clock_evidence']['checked_at'] = end.isoformat()
                    bars.append(row)
                for samples, expected in ((first, 25), (steady, 0)):
                    count = 0
                    began = perf_counter()
                    result = decisions.resolve(path, bars, symbol=symbol, session='2026-10-19',
                        now=now, proof=proof(), root=PATCH)
                    samples.append(perf_counter()-began)
                    connections.append(count)
                    assert len(result) == expected
        finally:
            sqlite3.connect = native_connect
    output = dict(test_only=True, source_path=str(decisions.__file__),
        source_sha256=sha256(Path(decisions.__file__).read_bytes()).hexdigest(),
        method_hash=common.digest(decisions.LOCAL_METHOD), symbols=20, minutes_per_symbol=25,
        fresh_seconds=first, unchanged_seconds=steady, connect_counts_in_call_order=connections,
        fresh_p95=sorted(first)[18], unchanged_p95=sorted(steady)[18],
        production_writes=0, market_latency_claim=False)
    with destination.open('x', encoding='utf-8') as stream:
        json.dump(output, stream, indent=2)
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
