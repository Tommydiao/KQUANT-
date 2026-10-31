"""Preserve a completed exact hour and its complete failure denominator."""
import argparse
from collections import Counter, defaultdict
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[4]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--run',required=True)
parser.add_argument('--projection',type=Path,required=True)
args=parser.parse_args()
if not args.run.replace('-','').isalnum():
    raise ValueError('INVALID_RUN_NAME')
run=ROOT/'source/evidence/new-machine-20261008'/args.run
projection_path=args.projection.resolve()
if not projection_path.is_relative_to((HERE/'release').resolve()):
    raise ValueError('PROJECTION_OUTSIDE_OVERLAY')
report_path=run/'topology_report.json'
report=json.loads(report_path.read_text(encoding='utf-8'))
projection=json.loads(projection_path.read_text(encoding='utf-8'))
frozen=json.loads((run/'TEST_ONLY-frozen-candidate.json').read_text(encoding='utf-8'))
if frozen['candidate_id']!=projection['candidate_id'] or frozen['candidate_payload_sha256']!=projection['candidate_payload_sha256']:
    raise ValueError('HOUR_CANDIDATE_MISMATCH')
if frozen['projection_sha256']!=sha256(projection_path.read_bytes()).hexdigest():
    raise ValueError('HOUR_PROJECTION_CHANGED')
if not report.get('continuous_60_minutes') or report['duration_seconds']<3600:
    raise ValueError('FULL_HOUR_NOT_COMPLETED')
accounting=report['legacy_included_transport_accounting']
lanes=defaultdict(Counter)
failures=[]
for file in sorted(run.glob('TEST_ONLY-query-transport-*.jsonl')):
    for line in file.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        prefix,payload=line.split(' ',1)
        if prefix!='status_query_attempt':
            raise ValueError('UNRECOGNIZED_QUERY_EVIDENCE')
        row=json.loads(payload)
        lanes[row['query_lane']][row['outcome']]+=1
        if row['outcome']!='SUCCESS':
            failures.append({key:row.get(key) for key in ('request_id','query_lane','observed_at',
                'outcome','returncode','process_ms','stages_ms','parent_pid','child_pid')})
totals=accounting['totals']
if sum(sum(counts.values()) for counts in lanes.values())!=totals['records']:
    raise ValueError('RAW_DENOMINATOR_MISMATCH')
reliability=not report['errors'] and accounting['complete'] and not totals['failure'] and not report['child_processes_alive']
summary=dict(schema='KQUANT_MATCHED_HOUR_VERDICT_V2',observed_at=datetime.now(UTC).isoformat(),
    candidate_id=projection['candidate_id'],payload_sha256=projection['candidate_payload_sha256'],
    projection_sha256=sha256(projection_path.read_bytes()).hexdigest(),
    report_path=str(report_path),report_sha256=sha256(report_path.read_bytes()).hexdigest(),
    duration_seconds=report['duration_seconds'],continuous_60_minutes=report['continuous_60_minutes'],
    source_match=report['tested_sources_unchanged'],frontend_match=report['tested_frontend_unchanged'],
    original_harness_assembly_pass=report['observation_assembly_pass'],
    comprehensive_reliability_pass=bool(reliability),performance_pass=report['performance_pass'],
    combined_pass=bool(reliability and report['performance_pass'] and report['tested_sources_unchanged'] and report['tested_frontend_unchanged']),
    release_ready=False,approval_requested=False,production_writes=0,test_only=True,
    totals=totals,query_lanes=dict(lanes),failures=failures,
    checkpoints=[{key:item.get(key) for key in ('checkpoint','registered_directions','identity_excluded',
        'evaluated_directions','unexplained_missing','segments','source_and_enqueue_seconds','source_fact_seconds')}
        for item in report['checkpoints']],
    children_alive=report['child_processes_alive'],
    recovery=[{key:item.get(key) for key in ('pending_before','restored','original_deadlines_preserved')}
        for item in report['crash_recovery']],
    manual=report['manual_http'],
    browser={key:report['real_browser'].get(key) for key in ('three_real_pages','refreshes','problems','signal_delivery_accepted')},
    http_classifications=dict(Counter(item['classification'] for item in report['http_failure_classification'])),
    original_report_errors=report['errors'],fixed_deadline_utc='2026-10-23T14:30:22Z',
    limits='All background failures retained; wall-time overlap is not an exemption. TEST_ONLY source/clock/model transport is not actual SDK, model capability, market latency, or natural signal acceptance.')
target=HERE/('hour-'+projection['candidate_id'].removeprefix('local-candidate-')+'-summary.json')
with target.open('x',encoding='utf-8') as stream:
    json.dump(summary,stream,indent=2)
print(json.dumps({'output':str(target),**{key:summary[key] for key in ('candidate_id','totals','query_lanes',
    'comprehensive_reliability_pass','performance_pass','combined_pass','children_alive')}},indent=2))
