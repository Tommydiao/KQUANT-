"""Read-only supplemental accounting; original topology verdicts stay intact."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE.parents[5] / 'source/evidence/new-machine-20261008'


def connect_recovery_match(trace, forwarded, upstream, code, fault):
    # A connect attempt is not cancelled when the replacement reports ready.
    return (trace.get('request_id') == forwarded and trace.get('path') == upstream
        and trace.get('status') == 503 and trace.get('error_code') == code
        and trace.get('failure_stage') == 'CONNECT' and trace.get('domain') == 'stocks'
        and code in {'UPSTREAM_TIMEOUT', 'UPSTREAM_CONNECTION_FAILED'}
        and fault['fault_monotonic_start'] <= trace.get('started_monotonic', -1)
            <= fault['replacement_ready_monotonic']
        and trace['started_monotonic'] <= trace.get('ended_monotonic', -1)
            <= fault['snapshot_ready_monotonic'])


def cold_receive_match(row, trace, proof, fault):
    try:
        returned = datetime.fromisoformat(proof['observed_at'])
        timed_out = datetime.fromisoformat(row['observed_at'])
        return (row.get('status') == trace.get('status') == 503
            and row.get('response_error_code') == trace.get('error_code') == 'UPSTREAM_TIMEOUT'
            and row.get('response_failure_stage') == trace.get('failure_stage') == 'RECEIVE'
            and row.get('response_error_origin') == 'GATEWAY_UPSTREAM'
            and trace.get('domain') == 'stocks'
            and row.get('server_request_id') == trace.get('request_id') == proof.get('request_id')
            and bool(row.get('server_request_id'))
            and urlsplit(row['path']).path == trace.get('path') == proof.get('path')
            and proof.get('pid') == fault['replacement_pid']
            and proof.get('stage') == 'HTTP_503' and proof.get('error') is None
            and any(c.get('kind') == 'compact' and c.get('strategy') == 'opening_momentum'
                    and c.get('has_value') is False and c.get('generation') == 0
                    and c.get('pending_key') is not None and c.get('error') is None
                    for c in proof.get('caches', []))
            and fault['fault_monotonic_start'] <= trace['started_monotonic']
                <= fault['replacement_ready_monotonic']
            and trace['started_monotonic'] <= trace['ended_monotonic']
                <= fault['snapshot_ready_monotonic']
            and 0 <= (returned - timed_out).total_seconds() <= .1)
    except (KeyError, TypeError, ValueError):
        return False


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
                if connect_recovery_match(trace, forwarded, upstream, code, fault)]
            if matching and transport.get('pid') == topology['gateway']['pid'] and transport.get('backend_port'):
                crossed = any(t['ended_monotonic'] > fault['replacement_ready_monotonic'] for t in matching)
                item.update(finding=('EXACT_INFLIGHT_CONNECT_ACROSS_REPLACEMENT_READY' if crossed
                                     else 'EXACT_CONNECT_TRACE_TO_DECLARED_CRASH_TARGET'),
                            trace_count=len(matching), gateway_pid=transport['pid'],
                            killed_pid=fault['killed_pid'], backend_port=transport['backend_port'],
                            replacement_ready_monotonic=fault['replacement_ready_monotonic'],
                            connection_traces=matching)
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
            receive = [trace for trace in transport.get('records', [])
                       if any(cold_receive_match(row, trace, proof, fault) for proof in cold)]
            if receive and transport.get('pid') == topology['gateway']['pid']:
                item.update(finding='EXACT_REPLACEMENT_COLD_RESPONSE_AFTER_GATEWAY_TIMEOUT',
                            replacement_pid=fault['replacement_pid'], gateway_pid=transport['pid'],
                            connection_traces=receive, projection_proofs=cold)
                break
        failures.append(item)
    result = dict(run=name, test_only=True, original_verdict_unchanged=True, classifier_version=3,
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
    target = HERE / (name + '-summary-v2.json')
    target.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('run','background','http_failure_count','findings','performance_pass')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('runs', nargs='+')
    for run in parser.parse_args().runs:
        summarize(run)
