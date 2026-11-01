"""Offline differential microbenchmark; no provider, browser or business storage."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from statistics import median
import sys
from time import perf_counter

HERE = Path(__file__).resolve().parent
FIRST = HERE.parent.parent/'opening-first-hour'
sys.path.insert(0, str(FIRST))
from test_first_hour_summary import candidate, parent, payload, PARENT


if __name__ == '__main__':
    value = payload(11)
    assert candidate.compact_status(value) == parent.compact_status(value)
    timings = {}
    for label, module in [('parent', parent), ('candidate', candidate)]:
        values = []
        for _ in range(30):
            started = perf_counter()
            module.compact_status(value)
            values.append(perf_counter()-started)
        timings[label] = dict(n=len(values), median_seconds=median(values),
                             maximum_seconds=max(values), samples=values)
    result = dict(test_only=True, observed_at=datetime.now(timezone.utc).isoformat(),
        actual_output_equal=True, api_calls=0, production_access=False,
        not_market_latency=True, timings=timings, source_sha256={
            'parent': sha256(PARENT.read_bytes()).hexdigest(),
            'candidate': sha256((FIRST/'first_hour_summary.py').read_bytes()).hexdigest()})
    target = HERE/'summary-benchmark-20261101.json'
    if target.exists():
        raise ValueError('DO_NOT_OVERWRITE_BENCHMARK')
    target.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({name:{key:v for key,v in row.items() if key!='samples'}
                      for name,row in timings.items()}))
