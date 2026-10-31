"""Bounded read-only main-store diagnostics; never changes journal mode."""
import ast
from contextlib import closing
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
binding = json.loads((ROOT/'runtime/config/new-epoch-store-paths.json').read_text())
services = json.loads((ROOT/'runtime/work/option_foundation/runtime/services.json').read_text())
path = Path(binding['stores']['main'])
report = {'observed_at': datetime.now(UTC).isoformat(), 'main_path': str(path),
          'business_writes': 0, 'sdk_connections': 0, 'samples': [], 'failure_details': []}
for launch in services['launches']:
    if 'stock-options' not in launch['name']:
        continue
    log = Path(launch['stderr'])
    raw = log.read_bytes()
    if len(raw) > 8_000_000:
        raise ValueError('LOG_BOUND_EXCEEDED')
    report['log'] = {'path': str(log), 'sha256': sha256(raw).hexdigest(), 'bytes': len(raw)}
    for line in raw.decode('utf-8', 'replace').splitlines():
        if 'status_query_failed ' not in line:
            continue
        try:
            detail = ast.literal_eval(line.split('status_query_failed ', 1)[1])
        except (ValueError, SyntaxError):
            continue
        if detail.get('phase') == 'universe':
            report['failure_details'].append(detail)
for _ in range(5):
    started = time.monotonic()
    row = {'observed_at': datetime.now(UTC).isoformat()}
    try:
        with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=.1)) as db:
            db.execute('PRAGMA query_only=ON')
            db.set_progress_handler(lambda: time.monotonic()-started > 1, 1000)
            row['journal_mode'] = db.execute('PRAGMA journal_mode').fetchone()[0]
            row['locking_mode'] = db.execute('PRAGMA locking_mode').fetchone()[0]
            row['active_rows'] = db.execute("""SELECT COUNT(*) FROM stock_watchlist_members m
                JOIN stock_watchlist_groups g ON g.group_id=m.group_id
                WHERE m.status='active' AND g.is_active=1""").fetchone()[0]
            row['result'] = 'SUCCESS'
    except sqlite3.Error as exc:
        row.update(result='FAILED', error_type=type(exc).__name__,
                   sqlite_code=getattr(exc, 'sqlite_errorname', None))
    row['seconds'] = time.monotonic()-started
    report['samples'].append(row)
report['lock_holder'] = 'UNKNOWN'
out = HERE/('universe-lock-'+datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')+'.json')
with out.open('x', encoding='utf-8') as stream:
    json.dump(report, stream, indent=2)
print(json.dumps({'evidence': str(out), 'samples': report['samples'],
                  'failure_details': len(report['failure_details']), 'lock_holder': report['lock_holder']}))
