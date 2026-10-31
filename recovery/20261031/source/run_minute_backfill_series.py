"""Serial bounded quote-only batches; durable summaries contain no credentials."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
RUN_ID = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
OUT = ROOT / 'evidence' / ('minute-series-' + RUN_ID)


def main():
    OUT.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, str(ROOT / 'run_minute_backfill.py'),
               '--cache-name', 'native-20261007-v1',
               '--timestamp-contract', 'verified-naive-asia-shanghai',
               '--timestamp-evidence', str(ROOT / 'evidence/sdk-timestamp-contract-20261007T071652086437Z.json'),
               '--max-requests', '48', '--run-seconds', '48', '--timeout-seconds', '55']
    previous = None
    no_progress = 0
    for batch in range(1, 71):
        try:
            done = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                  encoding='utf-8', errors='replace', timeout=80)
            report = json.loads(done.stdout)
        except subprocess.TimeoutExpired:
            report = {'status': 'SERIES_BATCH_TIMED_OUT', 'requests': None}
        except (ValueError, OSError):
            report = {'status': 'SERIES_BATCH_INVALID_REPORT', 'requests': None}
        coverage = report.get('coverage', {})
        summary = {'observed_at': datetime.now(timezone.utc).isoformat(), 'batch': batch,
                   'status': report.get('status'), 'requests': report.get('requests'),
                   'coverage': coverage, 'receipt_path': report.get('receipt_path'),
                   'quota_restricted': report.get('quota_restricted', False),
                   'production_started': False, 'old_business_continuity': 'UNKNOWN'}
        (OUT / f'batch-{batch:03d}.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        brief = {k: v for k, v in summary.items() if k != 'coverage'}
        brief.update(accepted_minutes=coverage.get('accepted_unique_minutes'),
                     missing_minutes=coverage.get('missing_minutes'),
                     task_states=coverage.get('task_states'))
        print(json.dumps(brief, ensure_ascii=True), flush=True)
        status = report.get('status', '')
        signature = (coverage.get('accepted_unique_minutes'),
                     json.dumps(coverage.get('task_states', {}), sort_keys=True))
        no_progress = no_progress + 1 if signature == previous else 0
        previous = signature
        reason = None
        if status.startswith('BLOCKED_') or status in {
            'CACHE_INTEGRITY_BLOCKED', 'WORKER_FAILED', 'WORKER_TIMED_OUT',
            'BATCH_WRAPPER_FAILED', 'SERIES_BATCH_TIMED_OUT', 'SERIES_BATCH_INVALID_REPORT'}:
            reason = 'REQUIRES_CLASSIFIED_REVIEW'
        elif status == 'BATCH_FINISHED':
            reason = 'FINAL_BATCH_VISITED_AVAILABLE_TASKS_RETRY_EXHAUSTION_REQUIRES_AUDIT'
        elif status == 'MONTHLY_QUOTA_RESTRICTED' and report.get('stop_reason') is None:
            reason = 'QUOTA_ALLOWED_TASKS_VISITED_WITH_RETRY_LIMITS'
        elif report.get('requests') == 0 or no_progress >= 3:
            reason = 'NO_FURTHER_PROGRESS_WITH_CURRENT_SCOPE'
        elif batch == 70:
            reason = 'SERIES_BATCH_LIMIT_REACHED'
        if reason:
            summary['series_stop_reason'] = reason
            (OUT / 'final.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'series_stop_reason': reason, 'evidence_directory': str(OUT)}), flush=True)
            return


if __name__ == '__main__':
    main()
