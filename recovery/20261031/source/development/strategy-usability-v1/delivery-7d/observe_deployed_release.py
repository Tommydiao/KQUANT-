"""Bounded read-only post-release observation; never reads credentials or calls SDK."""
import argparse
from collections import Counter
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
RUNTIME = ROOT / 'runtime/work/option_foundation/runtime'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def age(now, value):
    return (now - datetime.fromisoformat(value.replace('Z', '+00:00'))).total_seconds()


def http(url):
    started = time.monotonic()
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            data = response.read(300001)
            result = {'status': response.status, 'bytes': len(data)}
            if len(data) <= 300000 and 'json' in response.headers.get('Content-Type', ''):
                body = json.loads(data)
                result['summary'] = {key: body.get(key) for key in
                    ('state', 'status', 'generated_at', 'revision', 'error_code') if key in body}
    except urllib.error.HTTPError as exc:
        result = {'status': exc.code}
    except Exception as exc:
        result = {'error': type(exc).__name__}
    return dict(result, seconds=time.monotonic() - started)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or not args.output.resolve().is_relative_to(HERE.resolve()):
        raise ValueError('NEW_LOCAL_EVIDENCE_PATH_REQUIRED')
    urls = {
        'live': 'http://127.0.0.1:8001/api/health/live',
        'page': 'http://127.0.0.1:8020/?workspace=options&view=signals',
        'current_unauthenticated': 'http://127.0.0.1:8020/api/options/opening-trend/current?research_strategy=opening_momentum',
        'compact_unauthenticated': 'http://127.0.0.1:8020/api/options/one-minute/status?research_strategy=opening_momentum&compact=true',
    }
    started = time.monotonic()
    rows = []
    while True:
        now = datetime.now(UTC)
        row = {'at': now.isoformat(), 'http': {}, 'logs': []}
        try:
            services = read(RUNTIME / 'services.json')
            worker = read(RUNTIME / 'one-minute-worker.json')['worker']
            row.update(candidate=services.get('backend_release'), state=services.get('state'),
                stage=services.get('stage'), session=services.get('run_session_id'),
                launcher=services.get('launcher_identity'), listeners=services.get('listeners'),
                heartbeat_age_seconds=age(now, services['checked_at']),
                worker={key: worker.get(key) for key in ('state', 'stage', 'loop_count',
                    'first_loop_at', 'last_cycle_at', 'thread_alive', 'research_ready',
                    'runtime_health', 'session', 'qualified_alerts_enabled', 'paper_enabled',
                    'real_orders_enabled')},
                worker_age_seconds=age(now, worker['last_cycle_at']),
                clock_state=(worker.get('clock_measurement') or {}).get('state'))
            for launch in services.get('launches', []):
                for kind in ('stdout', 'stderr'):
                    path = Path(launch[kind])
                    if path.is_file():
                        stat = path.stat()
                        row['logs'].append({'name': launch['name'], 'kind': kind,
                            'path': str(path), 'bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns})
        except Exception as exc:
            row['state_read_error'] = type(exc).__name__
        for key, url in urls.items():
            row['http'][key] = http(url)
        rows.append(row)
        elapsed = time.monotonic() - started
        complete = elapsed >= 600
        result = {'candidate': args.candidate, 'observed_at': now.isoformat(),
            'elapsed_seconds': elapsed, 'complete': complete, 'samples': rows,
            'read_only': True, 'sdk_connections': 0, 'business_writes': 0}
        temporary = args.output.with_suffix('.pending')
        temporary.write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding='utf-8')
        temporary.replace(args.output)
        print(json.dumps({'elapsed': round(elapsed, 2), 'state': row.get('state'),
            'loops': row.get('worker', {}).get('loop_count'),
            'heartbeat_age': row.get('heartbeat_age_seconds'),
            'http': {k: v.get('status', v.get('error')) for k, v in row['http'].items()}}), flush=True)
        if complete:
            break
        time.sleep(min(30, max(0.01, 600 - elapsed)))
    summary = {'candidate': args.candidate, 'elapsed_seconds': elapsed, 'sample_count': len(rows),
        'complete': complete, 'read_only': True,
        'observation_sha256': sha256(args.output.read_bytes()).hexdigest(),
        'same_session': len({r.get('session') for r in rows}) == 1,
        'all_expected_candidate': all(r.get('candidate') == args.candidate for r in rows),
        'all_main_loop': all(r.get('state') == 'RUNNING' and r.get('stage') == 'MAIN_LOOP' for r in rows),
        'all_worker_ready': all(r.get('worker', {}).get('research_ready') is True
            and r.get('worker', {}).get('thread_alive') is True for r in rows),
        'max_heartbeat_age_seconds': max(r.get('heartbeat_age_seconds', 9999) for r in rows),
        'max_worker_age_seconds': max(r.get('worker_age_seconds', 9999) for r in rows),
        'first_loop_count': rows[0].get('worker', {}).get('loop_count'),
        'last_loop_count': rows[-1].get('worker', {}).get('loop_count'),
        'http_counts': {key: dict(Counter(str(r['http'][key].get('status', r['http'][key].get('error'))) for r in rows)) for key in urls},
        'state_read_errors': [r['state_read_error'] for r in rows if 'state_read_error' in r],
        'authenticated_page_verified': False, 'market_window_pass': False,
        'natural_signal_pass': False, 'performance_pass': False}
    args.output.with_name(args.output.stem + '-summary.json').write_text(
        json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    main()
