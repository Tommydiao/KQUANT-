"""Read completed TEST_ONLY evidence without replacing the original verdict."""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
from hashlib import sha256
import json
import math
from pathlib import Path
import sqlite3

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE.parents[5] / 'source/evidence/new-machine-20261008'
WINDOW = 'OPENING_FIRST_HOUR_RESEARCH_V1'


def p95(values):
    return sorted(values)[math.ceil(.95 * len(values)) - 1] if values else None


def main(name):
    root = (EVIDENCE / name).resolve()
    if not root.is_relative_to(EVIDENCE) or not (root / 'TEST_ONLY.json').is_file():
        raise ValueError('EXPLICIT_TEST_ONLY_ROOT_REQUIRED')
    inputs = {}

    def read(path):
        raw = path.read_bytes()
        inputs[path.name] = sha256(raw).hexdigest()
        return raw.decode('utf-8')

    report = json.loads(read(root / 'topology_report.json'))
    if report.get('child_processes_alive'):
        raise ValueError('COMPLETED_CLEANUP_REQUIRED')
    points = [row['checkpoint'] for row in report['checkpoints']]
    scope = json.loads(read(root / 'TEST_ONLY-scope.json'))
    applicable = {row['symbol'] for row in scope['items'] if row['identity_status'] == 'verified'}
    expected = {(symbol, right, point) for symbol in applicable for right in ('CALL', 'PUT') for point in points}
    latest, first_full = {}, {}
    with closing(sqlite3.connect((root / 'TEST_ONLY-research.sqlite3').as_uri() + '?mode=ro',
                                uri=True, timeout=.2)) as db:
        db.execute('PRAGMA query_only=ON')
        rows = db.execute("SELECT payload_json FROM evaluations WHERE json_extract(payload_json,'$.window_id')=? ORDER BY rowid", (WINDOW,))
        for (data,) in rows:
            value = json.loads(data)
            variant = value.get('variant')
            position = (value['symbol'], value['right'], value.get('calculation_bar_end'))
            if (variant not in {'S0', 'S1'} or position not in expected
                    or not value['policy_id'].endswith('FIRST-HOUR-V1')):
                continue
            key = (variant, *position)
            latest[key] = value
            if value['state'] in {'NO_TRIGGER', 'NUMERIC_PASS'}:
                first_full.setdefault(key, value)
    # Raw progress includes successful commits, including INCOMPLETE and revisions.
    # Older records have no evaluation IDs; never infer their first-full latency.
    attempts = defaultdict(list)
    for path in sorted(root.glob('TEST_ONLY-progress-*.jsonl')):
        for line in read(path).splitlines():
            row = json.loads(line)
            seconds = row.get('runtime_timing', {}).get('enqueue_to_commit_seconds')
            if (row.get('research_strategy') == 'opening_momentum'
                    and row.get('bar_end') in points and seconds is not None):
                attempts[row['bar_end']].append(seconds)
    variants = {}
    for variant in ('S0', 'S1'):
        selected = {k[1:]: v for k, v in latest.items() if k[0] == variant}
        completed = {k[1:] for k in first_full if k[0] == variant}
        incomplete = [v for v in selected.values() if v['state'] == 'INCOMPLETE']
        variants[variant] = dict(expected_positions=len(expected), observed_positions=len(selected),
            missing_positions=sorted(expected - selected.keys()),
            ever_full_positions=len(completed), latest_full_positions=sum(
                v['state'] in {'NO_TRIGGER', 'NUMERIC_PASS'} for v in selected.values()),
            objects_ever_full_all_points=sum(all((s, r, p) in completed
                for r in ('CALL', 'PUT') for p in points) for s in applicable),
            applicable_objects=len(applicable),
            incomplete_reasons=dict(Counter(str((v['symbol'], tuple(v.get('reasons', [])))) for v in incomplete)),
            timely_full_positions=None, timely_objects_all_points=None,
            timeliness_limit='CONTROLLED_TEST_CLOCK_NOT_REAL_MARKET_TIMELINESS')
    per_point = [dict(checkpoint=p, committed_attempts=len(attempts[p]),
        all_committed_attempts_p95_seconds=p95(attempts[p]),
        all_committed_attempts_max_seconds=max(attempts[p], default=None),
        original_first_result_p95_seconds=report['checkpoints'][i]['segments']['enqueue_to_commit_seconds']['p95_seconds'],
        first_full_by_variant={variant: data.get('first_full_enqueue_to_commit_p95_seconds')
            for variant, data in report['checkpoints'][i]['variants'].items()}) for i, p in enumerate(points)]
    first_full_proven = len(points) == 11 and all(
        data.get('first_full_timing_positions') == data.get('expected_legal_full')
        and data.get('first_full_enqueue_to_commit_p95_seconds') is not None
        for point in report['checkpoints'] for data in point['variants'].values())
    value = dict(schema='ITERATION_SUPPLEMENTAL_ADJUDICATION_V1', run=name, test_only=True,
        original_report_unchanged=True, source_sha256=inputs,
        original_seven_day_verdict='FAIL_UNCHANGED', variants=variants, checkpoints=per_point,
        all_committed_attempts_under_10s=len(points) == 11 and all(
            p95(attempts[p]) is not None and p95(attempts[p]) <= 10 for p in points),
        original_first_result_performance_pass=report.get('limited_research_performance_pass'),
        first_full_latency_proven=first_full_proven,
        measurement_gap=None if first_full_proven else 'NO_COMPLETE_FIRST_FULL_IDENTITY_LINKED_TIMING_DENOMINATOR',
        page_latency_p95_seconds=None, live_market_acceptance=False, publication_approved=False)
    target = HERE / (name + '-adjudication.json')
    target.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(path=str(target), variants=variants,
        all_committed_attempts_under_10s=value['all_committed_attempts_under_10s'],
        first_full_latency_proven=first_full_proven)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('runs', nargs='+')
    for run in parser.parse_args().runs:
        main(run)
