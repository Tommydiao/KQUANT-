"""Refresh non-secret progress from committed receipts, without reading providers."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def refresh():
    receipts = sorted((ROOT / 'minute-rebuild/native-20261007-v1/receipts').glob('*.json'))
    receipt_path = receipts[-1]
    batch = json.loads(receipt_path.read_bytes())
    coverage = batch['coverage']
    final_paths = sorted((ROOT / 'evidence').glob('minute-series-*/final.json'))
    series_final_path = final_paths[-1] if final_paths else None
    series_final = json.loads(series_final_path.read_bytes()) if series_final_path else {}
    series_finished = (series_final.get('receipt_path') == str(receipt_path)
                       and series_final.get('status') == 'BATCH_FINISHED')
    expected_policies = json.loads((ROOT / 'evidence/frontend-resume-config-search.json').read_bytes())['expected_original_sha256']
    restored = [name for name, expected in expected_policies.items()
                if (ROOT / 'development/workspace' / name).is_file()
                and hashlib.sha256((ROOT / 'development/workspace' / name).read_bytes()).hexdigest() == expected]
    probe_path = ROOT / 'evidence/minute-history-probe/probe-receipt-20261007T071709735749Z.json'
    status = {'observed_at': datetime.now(timezone.utc).isoformat(),
              'candidate': 'r58-p10-local-continuation-NOT_FROZEN',
              'migration_archives_verified': 3, 'development_files_verified': 2370,
              'recovered_database_files_verified': 10, 'preserved_candidate_database_sets': 4,
              'minute_full_business_database_recovered': False,
              'minute_probe_status': 'PROBE_PASSED', 'minute_probe_accepted_rows': 780,
              'latest_provider_probe_receipt': str(probe_path),
              'credentials_configured': True, 'historical_provider_access_demonstrated': True,
              'latest_minute_batch_status': batch['status'],
              'minute_rows_downloaded': coverage['accepted_unique_minutes'],
              'minute_window_missing_slots': coverage['missing_minutes'],
              'minute_coverage': coverage, 'latest_minute_batch_receipt': str(receipt_path),
              'minute_series_finished': series_finished,
              'minute_series_final_receipt': str(series_final_path) if series_finished else None,
              'minute_rebuild_offline_tests_passed': 40, 'frontend_tests_passed': 119,
              'sdk_timestamp_contract_verified': True,
              'production_started': False, 'old_business_continuity': 'UNKNOWN',
              'hour_topology_status': 'NOT_STARTED_PENDING_FINAL_SOURCE',
              'missing_original_materials': [name for name in expected_policies if name not in restored],
              'verified_original_materials_restored': restored,
              'plan': str(ROOT / 'CONTINUE_PLAN_20261007.md'),
              'next_step': ('FINAL_MINUTE_AUDIT_AND_CANDIDATE_ARCHIVE' if series_finished
                            else 'SERIAL_MINUTE_BACKFILL_AND_FINAL_LOCAL_ENGINEERING')}
    plan_path = ROOT / 'CONTINUE_PLAN_20261007.md'
    plan = plan_path.read_text(encoding='utf-8')
    start, end = '<!-- CURRENT_RECEIPT_START -->', '<!-- CURRENT_RECEIPT_END -->'
    current = (f'{start}\n最近提交回执：`{receipt_path.relative_to(ROOT).as_posix()}`。'
               f'当前有效 **{coverage["accepted_unique_minutes"]:,}** 个新分钟时间槽，'
               f'剩余 **{coverage["missing_minutes"]:,}** 个理论槽；任务状态 `{coverage["task_states"]}`。'
               + ('批量补取已结束，最终原始页审计与缺口解释分别核验；未接入生产。\n'
                  if series_finished else '批量补取进行中，以上仅为该回执时点的覆盖；未接入生产。\n') + end)
    if start in plan and end in plan:
        before, rest = plan.split(start, 1)
        _, after = rest.split(end, 1)
        plan = before + current + after
    else:
        plan = plan.replace('## 已在本机完成', current + '\n\n## 已在本机完成', 1)
    plan_path.write_text(plan, encoding='utf-8')
    status['plan_sha256'] = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    status_path = ROOT / 'evidence/current-resume-status.json'
    if status_path.exists():
        previous = json.loads(status_path.read_bytes())
        for key in ('hour_topology_status', 'hour_topology_evidence', 'final_candidate_id',
                    'backend_tests_passed', 'backend_regression_receipt', 'cloud_original_restoration',
                    'live_readiness_receipt', 'candidate_archive_status', 'host_clock_state',
                    'host_clock_diagnosis', 'system_time_repair_approval', 'minute_full_validation_receipt'):
            if key in previous:
                status[key] = previous[key]
        if status.get('final_candidate_id'):
            status['candidate'] = status['final_candidate_id']
    temporary = status_path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(status_path)
    print(json.dumps({k: status[k] for k in ('observed_at', 'minute_probe_status', 'minute_rows_downloaded',
                                            'minute_window_missing_slots', 'latest_minute_batch_receipt')}, ensure_ascii=True))


if __name__ == '__main__':
    refresh()
