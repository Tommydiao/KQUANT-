"""Read-only supplemental accounting; original topology verdicts stay intact."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE.parents[5] / 'source/evidence/new-machine-20261008'


def summarize(name):
    root = (EVIDENCE / name).resolve()
    if not root.is_relative_to(EVIDENCE) or not (root / 'TEST_ONLY.json').is_file():
        raise ValueError('TEST_ONLY_EVIDENCE_REQUIRED')
    inputs = {}
    def read(path):
        raw = path.read_bytes()
        inputs[path.name] = sha256(raw).hexdigest()
        return raw.decode('utf-8')
    report = json.loads(read(root / 'topology_report.json'))
    topology = json.loads(read(root / 'TEST_ONLY-topology.json'))
    transport = json.loads(read(root / 'TEST_ONLY-gateway-transport.json'))
    projections = [json.loads(line) for path in root.glob('TEST_ONLY-projection-errors-*.jsonl')
                   for line in read(path).splitlines()]
    samples = [json.loads(line) for path in root.glob('TEST_ONLY-http-*.jsonl')
               for line in read(path).splitlines()]
    failures = []
    for row in samples:
        if row.get('status') == 200:
            continue
        public = urlsplit(row['path']).path
        upstream = '/api/health/live' if public == '/api/stocks/health/live' else public
        forwarded = row.get('server_request_id')
        code = row.get('response_error_code')
        item = dict(request_id=row['request_id'], forwarded_request_id=forwarded,
                    path=row['path'], status=row.get('status'), error_code=code,
                    stage=row.get('response_failure_stage'), finding='UNATTRIBUTED')
        for fault in report.get('crash_recovery', []):
            contract = fault.get('http_contract') or {}
            allowed = {urlsplit(path).path: codes for path, codes in contract.get('allowed', {}).items()}
            start = row.get('monotonic_start', -1)
            end = start + row.get('seconds', 0)
            recovered = fault.get('initial_snapshots') or {}
            common = (row.get('status') == 503 and code in allowed.get(public, [])
                and fault.get('killed_pid') == topology['backend']['pid'] == contract.get('target_pid')
                and row.get('observer_pid') == topology['controller_pid'] == fault.get('observer_pid')
                and fault['fault_monotonic_start'] <= start <= end <= fault['snapshot_ready_monotonic']
                and row['seconds'] <= contract['max_request_seconds']
                and recovered.get('states') == {'current': 'FRESH', 'compact': 'FRESH'}
                and recovered.get('seconds', float('inf')) <= 5
                and fault['snapshot_ready_monotonic'] - fault['fault_monotonic_start'] <= contract['max_recovery_seconds'])
            if not common:
                continue
            matching = [trace for trace in transport.get('records', [])
                if trace.get('request_id') == forwarded and trace.get('path') == upstream
                and trace.get('status') == 503 and trace.get('error_code') == code
                and trace.get('failure_stage') == 'CONNECT' and trace.get('domain') == 'stocks'
                and fault['fault_monotonic_start'] <= trace['started_monotonic']
                    <= trace['ended_monotonic'] <= fault['replacement_ready_monotonic']]
            if matching and transport.get('pid') == topology['gateway']['pid'] and transport.get('backend_port'):
                item.update(finding='EXACT_CONNECT_TRACE_TO_DECLARED_CRASH_TARGET',
                            trace_count=len(matching), gateway_pid=transport['pid'],
                            killed_pid=fault['killed_pid'], backend_port=transport['backend_port'])
                break
            cold = [trace for trace in projections if trace.get('request_id') == forwarded
                    and trace.get('path') == public and trace.get('pid') == fault.get('replacement_pid')
                    and trace.get('stage') == 'HTTP_503' and trace.get('error') is None
                    and any(cache.get('kind') == 'compact' and cache.get('strategy') == 'opening_momentum'
                            and cache.get('has_value') is False and cache.get('generation') == 0
                            and cache.get('pending_key') is not None and cache.get('error') is None
                            for cache in trace.get('caches', []))]
            if code == 'TREND_STATUS_UNAVAILABLE' and cold:
                item.update(finding='EXACT_REPLACEMENT_COLD_SNAPSHOT', replacement_pid=fault['replacement_pid'],
                            snapshot_fresh_seconds=recovered['seconds'])
                break
        failures.append(item)
    result = dict(run=name, test_only=True, original_verdict_unchanged=True,
        os_network_root_claimed=False, source_sha256=inputs, errors=report.get('errors'),
        background=report.get('legacy_included_transport_accounting', {}).get('totals'),
        source_unchanged=report.get('tested_sources_unchanged'),
        children_alive=report.get('child_processes_alive'),
        performance_pass=report.get('performance_pass'),
        browser_classification=report.get('real_browser', {}).get('api_failure_classification'),
        browser_problems=report.get('real_browser', {}).get('problems'),
        http_attempts=len(samples), http_failure_count=len(failures),
        findings=dict(Counter(row['finding'] for row in failures)), failures=failures,
        checkpoints=[dict(at=p['checkpoint'], variants=p['variants'], segments=p['segments'])
                     for p in report.get('checkpoints', [])])
    target = HERE / (name + '-summary.json')
    target.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('run','background','http_failure_count','findings','performance_pass')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('runs', nargs='+')
    for run in parser.parse_args().runs:
        summarize(run)
