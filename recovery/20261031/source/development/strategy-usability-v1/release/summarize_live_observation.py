import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(r'E:\kquant 1007\KQUANT-Resume-Latest')
HERE = Path(__file__).parent / 'local-candidate-6ac8a5653d14a392'
def read(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))
report = read(HERE / 'live-observation.json')
assert report['complete'] and report['elapsed_seconds'] >= 600
samples = report['samples']
worker = read(ROOT / 'runtime/work/option_foundation/runtime/one-minute-worker.json')
w = worker['worker']
services = read(ROOT / 'runtime/work/option_foundation/runtime/services.json')
result = {'at': datetime.now(timezone.utc).isoformat(), 'candidate': report['candidate'],
    'elapsed_seconds': report['elapsed_seconds'], 'samples': len(samples),
    'same_run_session': len({s['session'] for s in samples}) == 1,
    'all_main_loop': all(s['state'] == 'RUNNING' and s['stage'] == 'MAIN_LOOP' for s in samples),
    'maximum_heartbeat_age_seconds': max(s['heartbeat_age_seconds'] for s in samples),
    'live_http_200': sum(s['http']['live'].get('status') == 200 for s in samples),
    'page_http_200': sum(s['http']['page'].get('status') == 200 for s in samples),
    'unauthenticated_current_401': sum(s['http']['current'].get('status') == 401 for s in samples),
    'authenticated_page_sse_verified': False, 'user_reported_login': True,
    'worker': {k: w.get(k) for k in ('state', 'stage', 'loop_count', 'first_loop_at', 'last_cycle_at', 'thread_alive', 'runtime_health', 'session', 'qualified_alerts_enabled', 'paper_enabled', 'real_orders_enabled')},
    'scope_count': len(w.get('registered_items', [])), 'clock_state': w.get('clock_measurement', {}).get('state'),
    'process_identities': services.get('listeners'), 'performance_pass': False,
    'natural_signal_pass': False, 'startup_status_deadline_preserved': True,
    'observation_sha256': hashlib.sha256((HERE / 'live-observation.json').read_bytes()).hexdigest()}
(HERE / 'live-observation-summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result, indent=2))
