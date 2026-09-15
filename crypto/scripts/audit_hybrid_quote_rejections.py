"""Descriptive immutable quote audit; never requalify rejected observations."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path


def summarize(rows):
    groups = defaultdict(lambda: {'count': 0, 'positions': Counter(), 'width': [], 'source_minus_lower': []})
    for row in rows:
        source, lower, upper = (row[k] for k in ('source_time', 'received_at_lower', 'received_at_upper'))
        if not all(math.isfinite(v) for v in (source, lower, upper)) or lower > upper:
            raise ValueError('Invalid archived quote bounds')
        if source != row['source_event_time_native_ms'] / 1000:
            raise ValueError('Native source timestamp mismatch')
        g = groups[(row['symbol'], row['clock_validation'])]
        g['count'] += 1
        g['positions']['before_lower' if source <= lower else 'within_interval' if source <= upper else 'after_upper'] += 1
        g['width'].append(upper - lower)
        g['source_minus_lower'].append(source - lower)
    def quantiles(values):
        values = sorted(values)
        return {str(q): values[round((len(values) - 1) * q)] for q in (0, .5, .95, 1)}
    return {'scope': 'DESCRIPTIVE_TIME_UNCERTAINTY_NOT_REQUALIFICATION',
            'changes_freshness': False, 'causal_clock_error_proven': False,
            'groups': [{'symbol': s, 'reason': reason, 'count': g['count'],
                        'source_positions': dict(g['positions']),
                        'interval_width_seconds': quantiles(g['width']),
                        'source_minus_lower_seconds': quantiles(g['source_minus_lower'])}
                       for (s, reason), g in sorted(groups.items())]}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--quotes', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    before = hashlib.sha256(a.quotes.read_bytes()).hexdigest()
    with a.quotes.open(encoding='utf-8') as f:
        result = summarize(json.loads(line) for line in f if line.strip())
    if hashlib.sha256(a.quotes.read_bytes()).hexdigest() != before:
        raise ValueError('Quote archive changed during audit')
    result['input_sha256'] = before
    a.output.mkdir(parents=True, exist_ok=False)
    (a.output / 'report.json').write_text(json.dumps(result, sort_keys=True), encoding='utf-8')
    print(json.dumps(result))
