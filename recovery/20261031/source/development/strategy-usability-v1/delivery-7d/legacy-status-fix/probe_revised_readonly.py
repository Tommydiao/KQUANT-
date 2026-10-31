"""Exercise the delta query against existing stores without installing or writing it."""
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BINDING = ROOT/'runtime/config/new-epoch-store-paths.json'
raw = BINDING.read_bytes()
os.environ.update(KQUANT_RUNTIME_DATA_ROOT=str(ROOT/'runtime'),
    KQUANT_RUNTIME_PATH_BINDING=str(BINDING), KQUANT_RUNTIME_PATH_BINDING_SHA256=sha256(raw).hexdigest())
from overlay import install
_, _, worker = install()
main = Path(json.loads(raw)['stores']['main'])
actual_cli = '--actual-cli' in sys.argv
if actual_cli:
    os.environ.update(KQUANT_TEST_LEGACY_OVERLAY=str(HERE),
        PYTHONPATH=str(HERE/'tools')+os.pathsep+str(ROOT/'source/development/workspace'))


def child(context):
    started = time.perf_counter()
    try:
        result = worker._phase('query', lambda: worker.query(main, history_context=context))
        encoded = worker._phase('encode', lambda: json.dumps(result).encode())
        worker._phase('ipc', lambda: worker._write_encoded(encoded))
    except Exception as exc:
        value = {'_status_error': worker.safe_failure(exc,
            phase=getattr(exc, 'status_query_phase', 'query'),
            elapsed_ms=(time.perf_counter()-started)*1000)}
        worker._write_encoded(json.dumps(value).encode())
        raise SystemExit(1)


if '--child' in sys.argv:
    child(json.loads(sys.argv[-1]))
else:
    report = {'observed_at': datetime.now(UTC).isoformat(), 'business_writes': 0, 'sdk_connections': 0,
        'deployed': False, 'parent_timeout_seconds': 2, 'sqlite_budget_seconds': 1,
        'assembly_scope': ('actual load_one_minute and python -m CLI/IPC; explicit module overlay, not full service assembly'
            if actual_cli else 'actual query/functions/IPC; explicit overlay loader, not full service assembly'),
        'files': {p.relative_to(HERE/'patches').as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in (HERE/'patches/kquant').rglob('*.py')},
        'attempts': []}
    for _ in range(5):
        attempt = {'started_at': datetime.now(UTC).isoformat()}
        started = time.perf_counter()
        try:
            if actual_cli:
                value = worker.load_one_minute(main)
                attempt['parent_history_context_ms'] = value['history_context_ms']
            else:
                context = worker.one_minute_history_context()
                attempt['parent_history_context_ms'] = (time.perf_counter()-started)*1000
                value = worker.run_json([sys.executable, '-B', str(Path(__file__).resolve()), '--child',
                    json.dumps(context)], diagnostics=True, lane='one_minute:status')
            attempt.update(outcome='SUCCESS', summary=value['summary'], bar_summary=value['bar_summary'],
                transport=value['query_transport'], response_bytes=len(json.dumps(value).encode()))
        except Exception as exc:
            attempt.update(outcome='FAILED', error_type=type(exc).__name__,
                diagnostic=getattr(exc, 'diagnostic', None), error=str(exc)[:300])
        attempt['whole_loader_seconds'] = time.perf_counter()-started
        report['attempts'].append(attempt)
    report['successes'] = sum(row['outcome'] == 'SUCCESS' for row in report['attempts'])
    output = ('readonly-cli-rowid-results.json' if '--rowid' in sys.argv else
              'readonly-cli-results.json' if actual_cli else 'readonly-revised-results.json')
    with (HERE/output).open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report))
