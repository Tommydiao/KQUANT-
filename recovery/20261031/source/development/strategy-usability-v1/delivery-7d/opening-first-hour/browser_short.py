"""Real compiled UI/API/Gateway; explicit isolated TCP-thread short test, not hour."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from pytest import MonkeyPatch
from short_probe import prepare, inputs
from first_hour import policies
import first_hour_store as store

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = ROOT/'source/development/workspace'
sys.path[:0] = [str(BASE/'tests'), str(BASE/'crypto')]
from test_positive_contract_tcp import tcp_server
from kquant.config import KquantConfig
from kquant.dashboard.app import create_app
from kquant.security import generate_password_hash
from kquant_crypto.gateway import create_gateway_app


def main():
    out = HERE/('browser-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    out.mkdir()
    path = out/'TEST_ONLY-research.sqlite3'
    args, sample, stages, transport = prepare(path)
    control = out/'clock-control.json'
    control.write_text('{"advance_seconds":0}', encoding='utf-8')
    start = time.monotonic()
    def clock():
        advance = json.loads(control.read_text(encoding='utf-8'))['advance_seconds']
        return args['now']+timedelta(seconds=time.monotonic()-start+advance)
    dist = HERE/'build/unified'
    report = dict(test_only=True, synthetic_transport=True, natural_signal=False,
        production_writes=0, sdk_calls=0, supervisor_assembly=False,
        process_topology='real API and Gateway TCP threads; separate headless browser',
        window_id=policies()['S0']['window_id'], policy_hashes={k:v['policy_hash'] for k,v in policies().items()},
        selection_stages=stages, frontend_hashes={str(p.relative_to(dist)): hashlib.sha256(p.read_bytes()).hexdigest()
                                                for p in dist.rglob('*') if p.is_file()})
    with MonkeyPatch.context() as patch:
        env = {'LOCALAPPDATA': str(out/'local'), 'KQUANT_REQUIRE_API_AUTH': 'true',
            'KQUANT_REALTIME_SUPERVISOR_ENABLED':'false', 'KQUANT_OPTION_RADAR_ENABLED':'false',
            'KQUANT_API_AUTH_TOKEN':'TEST_ONLY-first-hour-token', 'KQUANT_WORKSPACE_LOGIN_ENABLED':'true',
            'KQUANT_WORKSPACE_LOGIN_EMAIL':'test-only@example.invalid',
            'KQUANT_WORKSPACE_LOGIN_PASSWORD_HASH':generate_password_hash('TEST_ONLY_not_a_user_password'),
            'KQUANT_WORKSPACE_SESSION_SECRET':'TEST_ONLY_FIRST_HOUR_SECRET'*4}
        for key, value in env.items():
            patch.setenv(key, value)
        patch.delenv('KQUANT_OPTION_FOUNDATION_ROOT', raising=False)
        app = create_app(config=KquantConfig(db_path=out/'TEST_ONLY-main.sqlite3', outputs_dir=out/'outputs'),
                         research_store=path, research_clock=clock, manual_store=out/'TEST_ONLY-manual.sqlite3')
        snapshots = app.state.research_http_snapshots
        snapshots.worker = lambda: {'session': sample['session'], 'scope_hash': sample['scope_hash']}
        snapshots.observer = lambda: {'state':'TEST_ONLY', 'enforced':False}
        snapshots.strategy_availability = lambda s: {'enabled':s == 'opening_momentum'}
        snapshots.on_tick = None
        patch.setattr('kquant.status_worker.load_opening_trend', lambda *a,**kw: store.status(
            path=path, session=sample['session'], scope_hash=sample['scope_hash'], now=clock(),
            policy=policies()['S0'], compact=True))
        patch.setattr('kquant.status_worker.load_current_cards', lambda *a,**kw: store.current_cards(
            path=path, session=sample['session'], scope_hash=sample['scope_hash'], now=clock(), policy=policies()['S0']))
        for kind in ('current', 'compact'):
            try:
                value = snapshots.loader('opening_momentum', kind, snapshots.worker())
                report[kind+'_preflight'] = {'evaluations': len(value.get('evaluations', []))}
            except Exception as exc:
                import traceback
                report[kind+'_preflight'] = {'error': type(exc).__name__, 'traceback': traceback.format_exc()}
        if any('error' in report[kind+'_preflight'] for kind in ('current', 'compact')):
            report['returncode'] = 2
            (out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            snapshots.close()
            print(json.dumps({'out':str(out), 'preflight':{k:v for k,v in report.items() if k.endswith('_preflight')}}))
            return 2
        snapshots.start()
        try:
            with tcp_server(app, lifespan='off') as backend:
                gateway = create_gateway_app(stocks_url=backend, crypto_url=backend, web_dist_dir=dist,
                                              stocks_api_token='TEST_ONLY-first-hour-token')
                with tcp_server(gateway) as url:
                    config = dict(out=str(out), url=url, target='TEST CALL S0 S1',
                        control=str(control), contract=transport.contract_id, test_clock=clock().isoformat(),
                        playwright_module=r'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\playwright',
                        browser_executable=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
                    config_path = out/'browser-config.json'
                    config_path.write_text(json.dumps(config), encoding='utf-8')
                    proc = subprocess.run([r'C:\Program Files\nodejs\node.exe', str(HERE/'browser_short.cjs'), str(config_path)],
                                          capture_output=True, text=True, timeout=120)
                    report.update(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
        finally:
            snapshots.close()
    (out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'out':str(out), 'returncode':report.get('returncode'), 'stderr':report.get('stderr')}))
    return report.get('returncode', 1)


if __name__ == '__main__':
    raise SystemExit(main())
