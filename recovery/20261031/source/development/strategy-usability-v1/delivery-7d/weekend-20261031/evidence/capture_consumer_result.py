"""Bind completed isolated runs without replacing their original verdicts."""
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
RUNS = ROOT / 'source/evidence/new-machine-20261008'
NAMES = ('agent-consumer-short8-20261101', 'agent-consumer-short9-20261101',
         'agent-consumer-hour3-20261101')


def main():
    proofs, rows, identities = [], [], []

    def read(path):
        raw = path.read_bytes()
        proofs.append(dict(path=path.relative_to(ROOT).as_posix(), sha256=sha256(raw).hexdigest()))
        return json.loads(raw)

    for name in NAMES:
        report = read(RUNS / name / 'topology_report.json')
        summary = read(HERE / (name + '-summary-v2.json'))
        audit = read(HERE / (name + '-adjudication.json'))
        if report.get('child_processes_alive'):
            raise ValueError('TEST_CHILDREN_NOT_CLEANED')
        identities.append(json.dumps([report['tested_source_sha256'], report['tested_frontend_sha256']],
                                     sort_keys=True))
        original_unexplained = {r['request_id'] for r in report['http_failure_classification']
                                if r['classification'] == 'UNEXPLAINED'}
        attributed = {r['request_id'] for r in summary['failures']
                      if r['finding'] in {'EXACT_CONNECT_TRACE_TO_DECLARED_CRASH_TARGET',
                          'EXACT_INFLIGHT_CONNECT_ACROSS_REPLACEMENT_READY',
                          'EXACT_REPLACEMENT_COLD_SNAPSHOT',
                          'EXACT_REPLACEMENT_COLD_RESPONSE_AFTER_GATEWAY_TIMEOUT'}}
        unresolved = original_unexplained - attributed
        unexpected_errors = [r for r in report['errors'] if r['code'] != 'UNEXPLAINED_HTTP_FAILURES']
        rows.append(dict(run=name, seconds=report['duration_seconds'],
            original_errors=report['errors'], original_full_acceptance=report['full_acceptance'],
            original_observation_assembly_pass=report['observation_assembly_pass'],
            supplemental_unattributed_request_ids=sorted(unresolved),
            other_errors=unexpected_errors, background=summary['background'],
            http_findings=summary['findings'], browser_problems=summary['browser_problems'],
            browser_signal_delivery_accepted=report['real_browser']['signal_delivery_accepted'],
            first_full_p95=[{v: p['variants'][v]['first_full_enqueue_to_commit_p95_seconds']
                            for v in ('S0', 'S1')} for p in report['checkpoints']],
            limited_research_performance_pass=report['limited_research_performance_pass'],
            excellent_performance_pass=report['performance_pass'],
            source_unchanged=report['tested_sources_unchanged'],
            frontend_unchanged=report['tested_frontend_unchanged'],
            all_attempts_under_10s=audit.get('all_committed_attempts_under_10s'),
            all_attempt_checkpoint_measurements=audit['checkpoints'],
            child_processes_alive=report['child_processes_alive'],
            test_only=True, production=False))
    same_identity = len(set(identities)) == 1
    result = dict(schema='KQUANT_CONSUMER_SOURCE_REPAIR_RESULTS_V1',
        observed_at=datetime.now(UTC).isoformat(), runs=rows, proofs=proofs,
        same_source_and_build_for_all_runs=same_identity,
        original_reports_unchanged=True, seven_day_verdict='FAIL_UNCHANGED',
        live_market_acceptance=False, new_paid_calls=0, production_started=False,
        source_methods_renewed=False, launch_approved=False,
        limitation='Isolated synthetic input and controlled clock; no real market completion claim.')
    target = HERE / 'agent-consumer-result-20261101.json'
    target.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(path=str(target), same_identity=same_identity,
                         hour_limited_performance=rows[-1]['limited_research_performance_pass'],
                         hour_original_errors=rows[-1]['original_errors'])))


if __name__ == '__main__':
    main()
