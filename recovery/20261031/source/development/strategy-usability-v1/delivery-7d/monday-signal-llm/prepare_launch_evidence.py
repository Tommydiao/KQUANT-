"""Bind a completed, reliable exact hour for the existing guarded launch tool.

This produces measured assembly evidence, never an OWNER acceptance.
"""
import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def proof(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--projection', type=Path, required=True)
    args = parser.parse_args()
    projection_path = args.projection.resolve()
    if not projection_path.is_relative_to((HERE / 'release').resolve()):
        raise ValueError('PROJECTION_OUTSIDE_OVERLAY')
    p = read(projection_path)
    summary_path = HERE / ('hour-' + p['candidate_id'].removeprefix('local-candidate-') + '-summary.json')
    s = read(summary_path)
    report_path = Path(s['report_path'])
    r = read(report_path)
    if (s['candidate_id'] != p['candidate_id']
            or s['payload_sha256'] != p['candidate_payload_sha256']
            or s['projection_sha256'] != proof(projection_path)['sha256']
            or s['report_sha256'] != proof(report_path)['sha256']):
        raise ValueError('EXACT_HOUR_BINDING_CHANGED')
    if not (s['continuous_60_minutes'] and s['duration_seconds'] >= 3600
            and s['source_match'] and s['frontend_match']
            and s['comprehensive_reliability_pass'] and r['observation_assembly_pass']
            and not s['original_report_errors'] and not s['children_alive']
            and s['totals']['failure'] == 0 and s['totals']['deadline'] == 0):
        raise ValueError('RELIABLE_MATCHED_HOUR_REQUIRED')
    if len(s['checkpoints']) != 5 or any(c['unexplained_missing'] for c in s['checkpoints']):
        raise ValueError('CHECKPOINT_ACCOUNTING_INCOMPLETE')
    if not s['recovery'] or any(not (x['pending_before'] > 0
            and x['restored'] == x['pending_before'] and x['original_deadlines_preserved'])
            for x in s['recovery']):
        raise ValueError('ORIGINAL_DEADLINE_RECOVERY_REQUIRED')
    evidence = dict(schema='KQUANT_EXACT_ASSEMBLY_LAUNCH_EVIDENCE_V1',
        observed_at=datetime.now(UTC).isoformat(), candidate_id=p['candidate_id'],
        candidate_payload_sha256=p['candidate_payload_sha256'], exact_candidate_binding=True,
        continuous_60_minutes=True, observation_assembly_pass=True,
        enqueue_to_commit_performance_pass=s['performance_pass'],
        comprehensive_pass=s['combined_pass'], errors=[], child_processes_alive=[],
        report=proof(report_path), summary=proof(summary_path),
        projection=proof(projection_path), owner_approval_created=False,
        actual_model_capability_pass=False, actual_market_pass=False,
        limits='Assembly only. Preserve performance failure and all source/model/market limits.')
    target = projection_path.parent / 'assembly-launch-evidence.json'
    with target.open('x', encoding='utf-8') as stream:
        json.dump(evidence, stream, indent=2)
        stream.write('\n')
    print(json.dumps({'path': str(target), 'sha256': proof(target)['sha256'],
        'assembly_pass': True, 'performance_pass': s['performance_pass'],
        'owner_approval_created': False}))


if __name__ == '__main__':
    main()
