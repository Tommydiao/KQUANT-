"""Read archived clocks; distinguish exception evidence from terminal-report time."""
import argparse
import hashlib
import json
from pathlib import Path


def audit(report, clock):
    segment = clock['segment']
    receipt = report['last_received_interval']
    if receipt['clock_segment_id'] != clock['segment_id']:
        raise ValueError('Last receipt and archived clock do not match')
    terminal = report['observed_until_monotonic']
    return {
        'scope': 'TERMINAL_REPORT_TIME_NOT_EXCEPTION_TIME',
        'last_receipt_segment_age': receipt['received_at_monotonic'] - segment['mono_anchor'],
        'terminal_segment_age': terminal - segment['mono_anchor'],
        'last_receipt_to_terminal_seconds': terminal - receipt['received_at_monotonic'],
        'exception_time_recorded': 'exception_observed_monotonic' in report.get('failure', {}),
        'exception_callsite_proven': False,
        'suspend_or_clock_reversal_proven': False,
        'continuity_pass': False,
        'limitation': 'Terminal report is generated after cleanup. Do not attribute the entire gap to receive or failure; historical exception timestamp is absent.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--clock', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    files = [args.run / 'report.json', args.clock]
    result = audit(*(json.loads(p.read_text(encoding='utf-8')) for p in files))
    result['input_sha256'] = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'report.json').write_text(json.dumps(result, sort_keys=True), encoding='utf-8')
    print(json.dumps(result))
