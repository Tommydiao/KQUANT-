"""One bounded read-only metadata inspection, with no SDK or business writes."""
from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
binding = json.loads((ROOT / 'runtime/config/new-epoch-store-paths.json').read_text())
connection = sqlite3.connect(Path(binding['stores']['minute']).as_uri() + '?mode=ro', uri=True, timeout=.1)
connection.execute('PRAGMA query_only=ON')
started = time.monotonic()
connection.set_progress_handler(lambda: time.monotonic() - started > 3, 1000)
result = {'observed_at': datetime.now(UTC).isoformat(), 'business_writes': 0, 'sdk_connections': 0}
try:
    result['indexes'] = connection.execute("SELECT name,sql FROM sqlite_master WHERE type='index' AND tbl_name='one_minute_evaluations'").fetchall()
    result['session_counts'] = connection.execute('SELECT session,COUNT(*) FROM one_minute_evaluations GROUP BY session').fetchall()
    session = max(row[0] for row in result['session_counts'])
    before = time.monotonic()
    rows = connection.execute('SELECT rowid,symbol,right_name,bar_end,state,created_at FROM one_minute_evaluations WHERE session=?', (session,)).fetchall()
    result['metadata_seconds'] = time.monotonic() - before
    result['metadata_rows'] = len(rows)
    result['session'] = session
    result['max_bar_end'] = max((row[3] for row in rows), default=None)
    result['latest_bar_rows'] = sum(row[3] == result['max_bar_end'] for row in rows)
    result['numeric_rows'] = sum(row[4] in ('NUMERIC_PASS', 'NUMERIC_PASS_EVENT_PENDING') for row in rows)
    result['distinct_directions'] = len({row[1:3] for row in rows})
    result['result'] = 'SUCCESS'
except Exception as exc:
    result.update(result='FAILED', error_type=type(exc).__name__, message=str(exc)[:300])
finally:
    connection.close()
result['elapsed_seconds'] = time.monotonic() - started
with (HERE / 'metadata-inspection.json').open('x', encoding='utf-8') as stream:
    json.dump(result, stream, indent=2)
print(json.dumps(result))
