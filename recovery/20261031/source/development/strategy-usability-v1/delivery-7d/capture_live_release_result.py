"""Small read-only release/accounting evidence without SDK, credentials or DB copy."""
from collections import Counter, defaultdict
from contextlib import closing
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BASE = ROOT / 'source/development/workspace'
RUNTIME = ROOT / 'runtime/work/option_foundation/runtime'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


entry = read(BASE / 'config/local_workspace_entry.json')
folder = HERE / 'release' / entry['candidate_id']
projection = read(folder / 'deployment-projection.json')
services = read(RUNTIME / 'services.json')
worker = read(RUNTIME / 'one-minute-worker.json')['worker']
binding = read(ROOT / 'runtime/config/new-epoch-store-paths.json')
source_config = read(BASE / 'config/review_acceptances/options_opening_trend_reference_sources.json')
changes = [{'target': row['target'], 'expected': row['sha256'],
    'actual': digest(BASE / row['target'])} for row in projection['changes']]
index = None
with closing(sqlite3.connect(Path(binding['stores']['opening_research']).as_uri() + '?mode=ro',
    uri=True, timeout=.05)) as connection:
    connection.execute('PRAGMA query_only=ON')
    index = connection.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name='trend_input_source'").fetchone()
attempts = {}
log_files = []
for launch in services['launches']:
    for kind in ('stdout', 'stderr'):
        path = Path(launch[kind])
        if not path.is_file():
            continue
        raw = path.read_bytes()
        if len(raw) > 8_000_000:
            raise ValueError('LOG_BOUND_EXCEEDED')
        log_files.append({'name': launch['name'], 'kind': kind, 'path': str(path),
            'bytes': len(raw), 'sha256': sha256(raw).hexdigest()})
        for line in raw.decode('utf-8', 'replace').splitlines():
            marker = 'status_query_attempt '
            if marker not in line:
                continue
            try:
                row = json.loads(line.split(marker, 1)[1])
            except ValueError:
                continue
            key = (row['parent_pid'], row['attempt_id'])
            attempts[key] = row
lanes = defaultdict(Counter)
for row in attempts.values():
    lanes[row.get('query_lane', 'UNKNOWN')][row.get('outcome', 'UNKNOWN')] += 1
last = max(attempts.values(), key=lambda row: row['attempt_id'], default={})
denominator = last.get('denominator', {})
complete_attempts = bool(attempts) and len(attempts) == denominator.get('attempts')
report = {'observed_at': datetime.now(UTC).isoformat(), 'candidate': entry['candidate_id'],
    'payload_sha256': projection['candidate_payload_sha256'],
    'entry_sha256': digest(BASE / 'config/local_workspace_entry.json'),
    'acceptance_sha256': digest(folder / 'owner-launch-acceptance.json'),
    'release_manifest': entry['runtime_manifest'], 'recovery_manifest': entry['recovery_manifest'],
    'all_twelve_live_hashes_match': all(r['expected'] == r['actual'] for r in changes),
    'changed_files': changes, 'minute_method': source_config.get('canonical_resolution_method'),
    'schema_index_sql': index[0] if index else None,
    'services': {k: services.get(k) for k in ('state','stage','checked_at','launcher_identity',
        'run_session_id','listeners','backend_release','recovery_count')},
    'worker': {k: worker.get(k) for k in ('state','stage','loop_count','last_cycle_at',
        'thread_alive','research_ready','runtime_health','session','qualified_alerts_enabled',
        'paper_enabled','real_orders_enabled')},
    'registered_items_count': len(worker.get('registered_items', [])),
    'clock_state': (worker.get('clock_measurement') or {}).get('state'),
    'query_transport': {'records_available': len(attempts), 'last_denominator': denominator,
        'complete_attempts': complete_attempts, 'lanes': dict(lanes),
        'last_observed_at': last.get('observed_at'),
        'failure_samples': [r for r in attempts.values() if r.get('outcome') != 'SUCCESS'][-5:]},
    'logs': log_files, 'sdk_connections': 0, 'business_writes': 0,
    'authenticated_ui_verified': False, 'live_reliability_pass': False,
    'synthetic_hour_result_does_not_override_actual_failures': True}
output = folder / ('runtime-evidence-' + datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ') + '.json')
with output.open('x', encoding='utf-8') as stream:
    json.dump(report, stream, indent=2)
print(json.dumps({'evidence': str(output), 'candidate': entry['candidate_id'],
    'hashes_match': report['all_twelve_live_hashes_match'], 'index': report['schema_index_sql'],
    'worker': report['worker'], 'query_transport': {k: v for k, v in report['query_transport'].items()
        if k != 'failure_samples'}}))
