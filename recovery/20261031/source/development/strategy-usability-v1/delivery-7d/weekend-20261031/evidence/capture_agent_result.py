"""Summarize completed isolated evidence. No service, SDK, secret or database I/O."""
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[4]
RUN = ROOT/'source/evidence/new-machine-20261008/agent-admission-short7-20261101'


def main():
    proofs = {}

    def read(path):
        raw = path.read_bytes()
        proofs[path.relative_to(ROOT).as_posix()] = sha256(raw).hexdigest()
        return json.loads(raw)

    report = read(RUN/'topology_report.json')
    summary = read(HERE/'evidence/agent-admission-short7-20261101-summary-v2.json')
    adjudication = read(HERE/'evidence/agent-admission-short7-20261101-adjudication.json')
    candidate = read(HERE/'evidence/agent-development-candidate-7a75d4a6c3d157e3.json')
    imports = read(HERE/'evidence/agent-materialized-imports-20261101.json')
    browser = read(HERE/'evidence/browser-20261101T123000Z/report.json')
    if report['child_processes_alive'] or not report['tested_sources_unchanged']:
        raise ValueError('COMPLETED_UNCHANGED_TEST_REQUIRED')
    per_point = [dict(checkpoint=p['checkpoint'], first_full_p95_seconds={
        variant: row['first_full_enqueue_to_commit_p95_seconds']
        for variant, row in p['variants'].items()}) for p in report['checkpoints']]
    result = dict(schema='KQUANT_PHASED_AGENT_EXECUTION_V1',
        observed_at=datetime.now(UTC).isoformat(), original_seven_day_verdict='FAIL_UNCHANGED',
        candidate_id=candidate['candidate_id'], candidate_sha256=candidate['payload_sha256'],
        accepted_entry_unchanged=True, production_started=False, business_data_written=False,
        new_paid_calls=0, budgets_accepted=False, publication_accepted=False, real_orders_enabled=False,
        stages={
            '0': 'DEVELOPMENT_SOURCE_CLOSURE_ONLY_EXECUTABLE_RELEASE_PENDING',
            '1': 'SHORT_LIMITED_PERFORMANCE_FAIL_NO_NEW_MATCHED_HOUR',
            '2': 'V2_TOOLS_OUTBOX_PAGE_IMPLEMENTED_ISOLATED_API_QUALITY_PENDING',
            '3': 'EXPERIMENT_AND_ENGINEERING_WORKFLOWS_NOT_IMPLEMENTED',
            '4': 'LOCAL_ORDER_SIMULATION_NOT_IMPLEMENTED',
            '5': 'ACCEPTANCE_DEPLOYMENT_AND_THREE_REAL_WINDOWS_PENDING',
            '6': 'DISABLED_FUTURE_SCOPE', '7': 'DISABLED_FUTURE_SCOPE'},
        short=dict(duration_seconds=report['duration_seconds'],
            reads=summary['background'], failures=summary['findings'],
            browser_api_classification=report['real_browser']['api_failure_classification'],
            browser_problems=report['real_browser']['problems'],
            crash_recovery=[{k: row[k] for k in ('pending_before', 'restored', 'original_deadlines_preserved')}
                            for row in report['crash_recovery']],
            variants=adjudication['variants'], checkpoints=per_point,
            limited_research_performance_pass=report['limited_research_performance_pass'],
            excellent_performance_pass=report['performance_pass'],
            errors=report['errors'], child_processes_alive=[]),
        materialized_imports=imports,
        browser_evidence=browser,
        real_market_timeliness=None, qualified_to_page_p95=None, natural_signal_acceptance=False,
        next_work=['REDUCE_ADMISSION_REPREPARATION_WITH_ORIGINAL_EPOCH_CAS_BOUNDARIES',
            'COMPLETE_V2_ASOF_DATA_BINDING_AND_RESEARCH_QUALITY_EVALUATION',
            'IMPLEMENT_PREREGISTERED_EXPERIMENTS_AND_REVIEWED_CHANGE_CANDIDATES',
            'IMPLEMENT_ISOLATED_LOCAL_ORDER_SIMULATION',
            'TWO_MATCHED_SHORTS_THEN_MATCHED_HOUR_BEFORE_EXACT_RELEASE_DECISION'],
        source_sha256=proofs,
        consistency='Sequential completed-file evidence; not a business database snapshot.')
    target = HERE/'evidence/agent-iteration-result-20261101.json'
    target.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(path=str(target), candidate_id=candidate['candidate_id'],
                         limited_research_performance_pass=result['short']['limited_research_performance_pass'])))


if __name__ == '__main__':
    main()
