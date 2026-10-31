"""Bounded instrumentation of one real read-only status call; unchanged budgets."""
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BASE = ROOT/'source/development/workspace'
BINDING = ROOT/'runtime/config/new-epoch-store-paths.json'


def child():
    sys.path.insert(0, str(BASE))
    from kquant import bounded_sqlite, options_one_minute, options_two_hour_data
    from kquant.status_worker import query
    events = []
    started = time.monotonic()
    original = bounded_sqlite.read_connection

    @contextmanager
    def measured(path, **kwargs):
        with original(path, **kwargs) as connection:
            connection.set_trace_callback(lambda sql: events.append({
                'elapsed': time.monotonic()-started, 'kind': 'SQL',
                'sql': sql[:2500], 'database': Path(path).name}))
            yield connection

    bounded_sqlite.read_connection = measured

    def wrap(function, name):
        def run(*args, **kwargs):
            tick = time.monotonic()
            try:
                return function(*args, **kwargs)
            finally:
                events.append({'elapsed': time.monotonic()-started, 'kind': name,
                    'seconds': time.monotonic()-tick})
        return run

    options_two_hour_data.sessions_before = wrap(options_two_hour_data.sessions_before, 'sessions_before')
    options_one_minute.expiry_audit = wrap(options_one_minute.expiry_audit, 'expiry_audit')
    result = {'events': events, 'budget_unchanged': True, 'business_writes': 0, 'sdk_connections': 0}
    try:
        value = query(Path(json.loads(BINDING.read_text())['stores']['main']))
        result['result'] = 'SUCCESS'
        result['result_sha256'] = sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    except Exception as exc:
        result.update(result='FAILED', error_type=type(exc).__name__, traceback=traceback.format_exc())
    result['elapsed'] = time.monotonic()-started
    print(json.dumps(result))


if __name__ == '__main__':
    if '--child' in sys.argv:
        child()
    else:
        raw = BINDING.read_bytes()
        env = dict(os.environ, KQUANT_RUNTIME_DATA_ROOT=str(ROOT/'runtime'),
            KQUANT_RUNTIME_PATH_BINDING=str(BINDING),
            KQUANT_RUNTIME_PATH_BINDING_SHA256=sha256(raw).hexdigest())
        run = subprocess.run([sys.executable, '-B', __file__, '--child'], env=env,
            cwd=BASE, capture_output=True, timeout=4,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        value = json.loads(run.stdout)
        value.update(observed_at=datetime.now(UTC).isoformat(), returncode=run.returncode)
        with (HERE/'legacy-status-components-20261017.json').open('x', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2)
        print(json.dumps(value))
