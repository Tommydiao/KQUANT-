"""Supplemental TEST_ONLY attribution; never rewrites original failure records."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE.parents[4]/'source/evidence/new-machine-20261008'


def classify(row, transport, topology, faults):
    result = dict(browser_request_id=row.get('request_id'),
        forwarded_request_id=row.get('server_request_id'), path=row.get('path'),
        original_classification=row.get('classification'),
        classification='UNRESOLVED', causal_network_root_proven=False,
        historical_verdict_changed=False)
    matches = [r for r in transport.get('records', [])
               if r.get('request_id') and r.get('request_id') == row.get('server_request_id')
               and r.get('path') == row.get('path') and r.get('status') == row.get('status')
               and r.get('error_code') == row.get('error_code')]
    result['matching_trace_count'] = len(matches)
    if not matches:
        result['reason'] = 'NO_EXACT_GATEWAY_REQUEST_TRACE'
        return result
    result['phase'] = sorted({r.get('failure_stage', 'UNKNOWN') for r in matches})
    result['classification'] = 'PHASE_IDENTIFIED_INJECTION_NOT_PROVEN'
    for trace in matches:
        for fault in faults:
            contract = fault.get('http_contract') or {}
            allowed = {urlsplit(path).path: codes for path, codes in contract.get('allowed', {}).items()}
            initial = fault.get('initial_snapshots') or {}
            start, end = trace.get('started_monotonic'), trace.get('ended_monotonic')
            valid = (row.get('status') == 503 and trace.get('failure_stage') == 'CONNECT'
                and row.get('error_code') in allowed.get(row.get('path'), [])
                and transport.get('pid') == topology.get('gateway', {}).get('pid')
                and fault.get('killed_pid') == topology.get('backend', {}).get('pid')
                and contract.get('target_pid') == fault.get('killed_pid')
                and fault.get('observer_pid') == topology.get('controller_pid')
                and trace.get('domain') == 'stocks' and transport.get('backend_port') is not None
                and isinstance(start, (int, float)) and isinstance(end, (int, float))
                and fault.get('fault_monotonic_start', float('inf')) <= start <= end
                and end <= fault.get('replacement_ready_monotonic', -1)
                and end-start <= contract.get('max_request_seconds', 0)
                and initial.get('states') == {'current': 'FRESH', 'compact': 'FRESH'}
                and initial.get('seconds', float('inf')) <= 5
                and fault.get('snapshot_ready_monotonic', float('inf'))
                    - fault.get('fault_monotonic_start', 0) <= contract.get('max_recovery_seconds', 0))
            if valid:
                result.update(classification='DECLARED_BACKEND_CONNECT_FAULT_CORRELATED',
                    killed_pid=fault['killed_pid'], gateway_pid=transport['pid'],
                    contract_sha256=contract.get('sha256'),
                    reason='EXACT_REQUEST_PHASE_PROCESS_AND_RECOVERY_CONTRACT_MATCH')
                return result
    result['reason'] = 'PHASE_KNOWN_BUT_NOT_ALL_INJECTION_CONTRACT_CONDITIONS_MET'
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run')
    args = parser.parse_args()
    root = (EVIDENCE/args.run).resolve()
    if not root.is_relative_to(EVIDENCE) or not (root/'TEST_ONLY.json').is_file():
        raise ValueError('ISOLATED_EVIDENCE_REQUIRED')
    files = {name: (root/name).read_bytes() for name in
        ('topology_report.json', 'TEST_ONLY-topology.json', 'TEST_ONLY-gateway-transport.json')}
    report, topology, transport = [json.loads(raw) for raw in files.values()]
    rows = [classify(r, transport, topology, report.get('crash_recovery', []))
        for r in report.get('real_browser', {}).get('api_failure_observations', [])
        if r.get('classification') != 'TEST_ONLY_UNMOUNTED']
    value = dict(test_only=True, run=args.run, rows=rows,
        source_sha256={name: sha256(raw).hexdigest() for name, raw in files.items()},
        does_not_override_original_verdict=True, performance_pass=report.get('performance_pass'),
        limits='Correlates exact gateway phase, terminated process and recovery contract; '
               'does not prove an unrecorded OS/network cause or waive any historical failure.')
    target = HERE/'evidence'/(args.run+'-http-attribution.json')
    target.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(path=str(target), rows=len(rows),
        classifications=[r['classification'] for r in rows])))


if __name__ == '__main__':
    main()
