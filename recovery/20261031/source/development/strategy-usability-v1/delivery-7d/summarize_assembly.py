"""Small evidence-backed verdict; synthetic assembly is never market acceptance."""
import argparse
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
EVIDENCE = ROOT/'source/evidence/new-machine-20261008'


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def summary(directory, projection):
    if not directory.resolve().is_relative_to(EVIDENCE.resolve()):
        raise ValueError('NOT_ISOLATED_EVIDENCE')
    report_path = directory/'topology_report.json'
    if not report_path.is_file():
        points = [load(p) for p in sorted(directory.glob('TEST_ONLY-checkpoint-*.json'))]
        return dict(observed_at=datetime.now(UTC).isoformat(), state='RUNNING_OR_INTERRUPTED_FINAL_REPORT_MISSING',
            checkpoint_count=len(points), final_acceptance=None, hour_complete=None)
    report, candidate = load(report_path), load(projection)
    frozen = load(directory/'TEST_ONLY-frozen-candidate.json')
    sources = report['tested_source_sha256']
    mapping = {row['target']: sources.get('delivery/patches/'+row['target']) == row['sha256']
        for row in candidate['changes']}
    bound = (frozen['candidate_id'] == candidate['candidate_id']
        and frozen['candidate_payload_sha256'] == candidate['candidate_payload_sha256']
        and frozen['projection_sha256'] == digest(projection)
        and sources.get('frozen-projection') == digest(projection) and all(mapping.values()))
    checkpoints = [dict(checkpoint=row['checkpoint'], registered_directions=row['registered_directions'],
        identity_excluded=row['identity_excluded'], evaluated_directions=row['evaluated_directions'],
        unexplained_missing=row['unexplained_missing'], states=row['states'],
        raw_revision_count=row['raw_evaluation_records'],
        enqueue_to_commit=row.get('segments', {}).get('enqueue_to_commit_seconds'),
        input_read=row.get('segments', {}).get('input_read_seconds'),
        calculation=row.get('segments', {}).get('calculation_seconds')) for row in report['checkpoints']]
    recovered = [dict(pending_before=r['pending_before'], restored=r['restored'],
        original_deadlines_preserved=r['original_deadlines_preserved'],
        snapshot_ready_seconds=r['snapshot_ready_monotonic']-r['fault_monotonic_start'])
        for r in report['crash_recovery']]
    browser = report.get('real_browser') or {}
    result = dict(observed_at=datetime.now(UTC).isoformat(), test_only=True,
        candidate_id=candidate['candidate_id'], candidate_payload_sha256=candidate['candidate_payload_sha256'],
        report=dict(path=str(report_path), sha256=digest(report_path)),
        projection=dict(path=str(projection), sha256=digest(projection)),
        exact_candidate_binding=bound, mapped_files=mapping,
        duration_seconds=report['duration_seconds'], continuous_60_minutes=report['continuous_60_minutes'],
        five_minute_cadence=report['five_minute_cadence'], source_unchanged=report['tested_sources_unchanged'],
        frontend_unchanged=report['tested_frontend_unchanged'],
        observation_assembly_pass=bool(bound and report['observation_assembly_pass']),
        enqueue_to_commit_performance_pass=report['performance_pass'],
        errors=report['errors'], child_processes_alive=report['child_processes_alive'],
        checkpoints=checkpoints, recovery=recovered,
        http=report['http'], http_failure_classes=dict(Counter(
            row['classification'] for row in report.get('http_failure_classification', []))),
        browser=dict(three_real_pages=browser.get('three_real_pages'), refreshes=browser.get('refreshes'),
            problems=browser.get('problems'), signal_delivery_accepted=browser.get('signal_delivery_accepted'),
            live_market_delivery_accepted=False),
        manual_http=report['manual_http'], sdk_connections=report['live_sdk_connections'],
        production_writes=report['production_writes'], market_acceptance=False,
        real_receive_to_compute_p95=None, real_qualification_to_page_p95=None,
        new_production_launch_accepted=False, old_running_service_unchanged=True)
    from tools.transport_audit import summarize
    result['background_query_transport'] = summarize(directory)
    result['background_query_transport']['source_sha256'] = {
        path: digest(Path(path)) for path in result['background_query_transport']['files']}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--projection', type=Path, required=True)
    parser.add_argument('--save', type=Path)
    args = parser.parse_args()
    result = summary(args.directory, args.projection)
    if args.save:
        if not args.save.resolve().is_relative_to(HERE.resolve()):
            raise ValueError('SUMMARY_OUTSIDE_DELIVERY')
        with args.save.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=True, indent=2)
    print(json.dumps(result, ensure_ascii=True, indent=2))
