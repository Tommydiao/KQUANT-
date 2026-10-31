import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(r'E:\kquant 1007\KQUANT-Resume-Latest')
OUT = Path(__file__).parent / 'local-candidate-6ac8a5653d14a392/live-observation.json'
services = ROOT / 'runtime/work/option_foundation/runtime/services.json'
urls = {'live': 'http://127.0.0.1:8001/api/health/live',
        'page': 'http://127.0.0.1:8020/?workspace=options&view=signals',
        'current': 'http://127.0.0.1:8020/api/options/opening-trend/current?research_strategy=opening_momentum',
        'compact': 'http://127.0.0.1:8020/api/options/one-minute/status?research_strategy=opening_momentum&compact=true'}
started = time.monotonic()
rows = []
while True:
    now = datetime.now(timezone.utc)
    value = json.loads(services.read_text(encoding='utf-8-sig'))
    checked = datetime.fromisoformat(value['checked_at'].replace('Z', '+00:00'))
    row = {'at': now.isoformat(), 'candidate': value.get('backend_release'),
           'state': value.get('state'), 'stage': value.get('stage'),
           'session': value.get('run_session_id'), 'heartbeat_age_seconds': (now-checked).total_seconds(),
           'listeners': value.get('listeners'), 'http': {}, 'logs': []}
    for key, url in urls.items():
        tick = time.monotonic()
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                data = response.read(300000)
                result = {'status': response.status, 'bytes': len(data)}
                if key != 'page':
                    try:
                        body = json.loads(data)
                        result['summary'] = {k: body[k] for k in ('state', 'status', 'generated_at', 'revision', 'error_code') if k in body}
                    except ValueError:
                        result['parse'] = 'NOT_JSON'
        except urllib.error.HTTPError as exc:
            result = {'status': exc.code}
        except Exception as exc:
            result = {'error': type(exc).__name__}
        result['seconds'] = time.monotonic()-tick
        row['http'][key] = result
    for launch in value.get('launches', []):
        for kind in ('stdout', 'stderr'):
            p = Path(launch[kind])
            if p.exists():
                st = p.stat()
                row['logs'].append({'name': launch['name'], 'kind': kind, 'bytes': st.st_size, 'mtime': st.st_mtime})
    rows.append(row)
    elapsed = time.monotonic()-started
    OUT.write_text(json.dumps({'candidate': 'local-candidate-6ac8a5653d14a392', 'elapsed_seconds': elapsed, 'complete': elapsed >= 600, 'samples': rows}, indent=2), encoding='utf-8')
    print(json.dumps({'elapsed': round(elapsed), 'state': row['state'], 'stage': row['stage'], 'age': round(row['heartbeat_age_seconds'], 2), 'http': {k: v.get('status', v.get('error')) for k,v in row['http'].items()}}), flush=True)
    if elapsed >= 600:
        break
    time.sleep(30)
