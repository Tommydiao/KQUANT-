"""Summarize completed matching evidence without changing original reports."""
from collections import Counter, defaultdict
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
run = ROOT/'source/evidence/new-machine-20261008/status-reliability-hour-4549-20261017'
report_path = run/'topology_report.json'
report = json.loads(report_path.read_text())
projection_path = HERE/'release/local-candidate-45492b7b0b7428ca/deployment-projection.json'
projection = json.loads(projection_path.read_text())
accounting = report['legacy_included_transport_accounting']
lanes = defaultdict(Counter)
failures = []
for file in run.glob('TEST_ONLY-query-transport-*.jsonl'):
    for line in file.read_text().splitlines():
        if not line.strip():
            continue
        prefix, payload = line.split(' ', 1)
        assert prefix == 'status_query_attempt'
        row = json.loads(payload)
        lanes[row['query_lane']][row['outcome']] += 1
        if row['outcome'] != 'SUCCESS':
            failures.append({key: row.get(key) for key in ('request_id','query_lane',
                'observed_at','outcome','returncode','stages_ms')})
points = []
for row in report['checkpoints']:
    points.append({key: row.get(key) for key in ('checkpoint','registered_directions',
        'identity_excluded','evaluated_directions','unexplained_missing','segments')})
summary = dict(schema='KQUANT_MATCHED_HOUR_VERDICT_V1', observed_at=datetime.now(UTC).isoformat(),
    candidate_id=projection['candidate_id'], payload_sha256=projection['candidate_payload_sha256'],
    projection_sha256=sha256(projection_path.read_bytes()).hexdigest(),
    report_path=str(report_path),report_sha256=sha256(report_path.read_bytes()).hexdigest(),
    duration_seconds=report['duration_seconds'], continuous_60_minutes=report['continuous_60_minutes'],
    source_match=report['tested_sources_unchanged'], frontend_match=report['tested_frontend_unchanged'],
    original_harness_assembly_pass=report['observation_assembly_pass'],
    comprehensive_reliability_pass=not report['errors'] and accounting['complete'] and not accounting['totals']['failure'],
    performance_pass=report['performance_pass'], release_ready=False,
    approval_requested=False, production_writes=0, test_only=True,
    totals=accounting['totals'],query_lanes=dict(lanes),failures=failures,checkpoints=points,
    children_alive=report['child_processes_alive'],
    recovery=[{key: item.get(key) for key in ('pending_before','restored','original_deadlines_preserved')}
        for item in report['crash_recovery']],
    manual=report['manual_http'],
    browser={key: report['real_browser'].get(key) for key in ('three_real_pages','refreshes','problems','signal_delivery_accepted')},
    http_classifications=dict(Counter(item['classification'] for item in report['http_failure_classification'])),
    original_report_errors=report['errors'],
    fixed_deadline_utc='2026-10-23T14:30:22Z',
    caveat='Original assembly flag precedes background accounting. Combined verdict is FAIL. No real market or natural Signal claim.')
output = HERE/'hour-4549-summary.json'
with output.open('x',encoding='utf-8') as stream:
    json.dump(summary,stream,indent=2)
print(json.dumps({key: summary[key] for key in ('candidate_id','totals','query_lanes',
    'comprehensive_reliability_pass','performance_pass','release_ready','children_alive')}))
