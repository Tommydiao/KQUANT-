"""Load private local credentials explicitly, then invoke the quote-only batch CLI."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'development/workspace'))
from kquant.local_env import load_market_data_env


if __name__ == '__main__':
    audit = load_market_data_env(path=ROOT / '.env')
    if not audit['longbridge_credentials_configured']:
        print(json.dumps({'status': 'BLOCKED_CREDENTIALS_MISSING', 'requests': 0}))
        raise SystemExit(2)
    done = subprocess.run([sys.executable, str(ROOT / 'minute_rebuild.py'), 'bounded-live', *sys.argv[1:]],
                          capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=70)
    try:
        report = json.loads(done.stdout)
    except ValueError:
        print(json.dumps({'status': 'BATCH_WRAPPER_FAILED', 'returncode': done.returncode}))
        raise SystemExit(2)
    summary = {k: v for k, v in report.items() if k not in ('results', 'tasks', 'unresolved_symbols', 'quota_scope')}
    if 'results' in report:
        summary['result_count'] = len(report['results'])
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    raise SystemExit(done.returncode)
