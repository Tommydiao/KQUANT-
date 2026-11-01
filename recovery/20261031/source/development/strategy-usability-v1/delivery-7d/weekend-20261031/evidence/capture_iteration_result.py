"""Summarize completed artifacts without changing their original verdicts."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[5]
EVIDENCE = ROOT/'source/evidence/new-machine-20261008'
RUNS = ['iteration-query-fixed-short4-20261101', 'iteration-query-fixed-short5-20261101',
        'iteration-query-fixed-hour2-20261101']


def main():
    reports, proofs = [], []
    for name in RUNS:
        path = EVIDENCE/name/'topology_report.json'
        raw = path.read_bytes()
        reports.append(json.loads(raw))
        proofs.append(dict(run=name, sha256=sha256(raw).hexdigest(), bytes=len(raw)))
    hour = reports[-1]
    identities = {key: all(row[key] == reports[0][key] for row in reports) for key in (
        'tested_source_sha256', 'tested_frontend_sha256', 'tested_frontend_source_sha256')}
    accounting = json.loads((HERE/(RUNS[-1]+'-summary-v2.json')).read_text())
    adjudication = json.loads((HERE/(RUNS[-1]+'-adjudication.json')).read_text())
    value = dict(schema='NOVEMBER_ITERATION_IMPLEMENTATION_CHECKPOINT_V1',
        captured_at=datetime.now(timezone.utc).isoformat(), originals=proofs,
        original_verdicts_unchanged=True, same_source_and_build=identities,
        duration_seconds=hour['duration_seconds'], errors=hour['errors'],
        children_alive=hour['child_processes_alive'], sources_unchanged=hour['tested_sources_unchanged'],
        frontend_unchanged=hour['tested_frontend_unchanged'],
        background=accounting['background'], transport_failure_findings=accounting['findings'],
        browser_problems=hour['real_browser']['problems'],
        browser_failure_classification=hour['real_browser']['api_failure_classification'],
        checkpoints=[dict(at=p['checkpoint'], variants=p['variants'], segments=p['segments'])
                     for p in hour['checkpoints']],
        fixed_denominator=adjudication['variants'],
        recovery=[{k: r[k] for k in ('pending_before', 'restored', 'original_deadlines_preserved')}
                  for r in hour['crash_recovery']],
        gates=dict(isolated_safety_assembly=hour['observation_assembly_pass'],
            excellent_2s=hour['performance_pass'], limited_10s=hour['limited_research_performance_pass'],
            actual_production_entry=None, qualification_to_page_p95=None,
            real_market_windows=None, natural_signal=None),
        production_changed=False, business_database_changed=False, paid_calls_this_implementation=0,
        exact_launch_accepted=False, production_fee_proposal_accepted=False,
        old_seven_day_verdict='FAIL_UNCHANGED',
        implementation_remaining=['last_two_checkpoint_admission_queue_latency',
            'three_runtime_test_bootstrap_dependencies_and_exact_release_entry',
            'research_review_v2_questions_local_evidence_and_tracking',
            'accurate_release_method_and_fee_acceptance', 'real_market_windows'])
    target = HERE/'iteration-result-20261101.json'
    target.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(path=str(target), same_version=identities,
        gates=value['gates'], background=value['background'], recovery=value['recovery'])))


if __name__ == '__main__':
    main()
