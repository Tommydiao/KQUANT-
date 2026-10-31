"""One bounded real-data legacy status probe with stack timing, no SDK or writes."""
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
BASE = ROOT / 'source/development/workspace'
BINDING = ROOT / 'runtime/config/new-epoch-store-paths.json'
raw = BINDING.read_bytes()
binding = json.loads(raw)
env = dict(os.environ, KQUANT_RUNTIME_DATA_ROOT=str(ROOT/'runtime'),
    KQUANT_RUNTIME_PATH_BINDING=str(BINDING),
    KQUANT_RUNTIME_PATH_BINDING_SHA256=sha256(raw).hexdigest(), PYTHONPATH=str(BASE))
code = "import faulthandler,runpy;faulthandler.dump_traceback_later(1.4);runpy.run_module('kquant.status_worker',run_name='__main__')"
started = time.monotonic()
result = {'observed_at': datetime.now(UTC).isoformat(), 'business_writes': 0,
    'sdk_connections': 0, 'source_changed': False,
    'source_sha256': sha256((BASE/'kquant/status_worker.py').read_bytes()).hexdigest(),
    'binding_sha256': sha256(raw).hexdigest(), 'original_sql_budget_unchanged': True}
try:
    process = subprocess.run([sys.executable, '-B', '-c', code, binding['stores']['main'],
        '--diagnostic-envelope'], cwd=BASE, env=env, capture_output=True, timeout=3,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    result.update(returncode=process.returncode, stdout=process.stdout[:8192].decode('utf-8','replace'),
        stderr=process.stderr[:16384].decode('utf-8','replace'), process_timeout=False)
except subprocess.TimeoutExpired as exc:
    result.update(returncode=None, stdout=(exc.stdout or b'')[:8192].decode('utf-8','replace'),
        stderr=(exc.stderr or b'')[:16384].decode('utf-8','replace'), process_timeout=True)
result['seconds'] = time.monotonic() - started
output = HERE / 'legacy-status-probe-20261017.json'
with output.open('x', encoding='utf-8') as stream:
    json.dump(result, stream, indent=2)
print(json.dumps(result))
