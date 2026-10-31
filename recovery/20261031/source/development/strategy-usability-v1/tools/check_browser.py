"""Actual compiled page/API/Gateway with isolated historical replay storage.

This is a UI bridge, not Supervisor assembly, live SDK, or OWNER acceptance.
"""
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from bootstrap import activate

DEV, BASE = activate()
sys.path[:0] = [str(BASE / 'tests'), str(BASE / 'crypto')]
from pytest import MonkeyPatch
from fastapi.responses import JSONResponse
from test_positive_contract_tcp import tcp_server
from kquant.config import KquantConfig
from kquant.dashboard.app import create_app
from kquant.security import generate_password_hash
from kquant import options_opening_momentum as model
from kquant import options_opening_trend_store as store
from kquant_crypto.gateway import create_gateway_app


def main():
    replay = sorted(p for p in (DEV / 'evidence').glob('replay-*') if (p / 'page_examples.json').exists())[-1]
    examples = json.loads((replay / 'page_examples.json').read_text(encoding='utf-8'))
    sample = next(row for row in examples if row['symbol'] == 'BTDR' and row['right'] == 'PUT')
    out = DEV / 'evidence' / ('browser-' + datetime.now(UTC).strftime('%Y%m%d-%H%M%S'))
    out.mkdir()
    dist = DEV / 'build/unified'
    database = replay / 'isolated-research.sqlite3'
    synthetic = '--synthetic-reference' in sys.argv
    if synthetic:
        sys.path.insert(0, str(DEV / 'tests'))
        from test_strategy_usability import inputs, pair
        from kquant import options_opening_trend_jobs as jobs
        from kquant.options_opening_trend_pipeline import step
        from kquant.options_opening_trend_current import current as current_trend
        from kquant import options_opening_momentum_journal as journal
        args = inputs()
        args['reference']['previous_close'] = None
        rows = pair(args)
        sample = rows[0]
        database = out / 'TEST_ONLY-reference.sqlite3'
        store.initialize(database)
        journal.initialize(database)
        store.persist(rows, database)
        stamp = args['now']
        class SyntheticTransport:
            def event(self, *a): return {'event_decision': {'decision': 'WARN'}, 'trade_eligible': True}
            def expiries(self, *a): return {'expiries': ['2026-10-06']}
            def chain(self, *a): return {'contracts': [{'call_symbol': 'TEST261006C105000.US', 'strike_price': 105}]}
            def greeks(self, *a): return {'items': [{'contract_symbol': 'TEST261006C105000.US', 'delta': .525}]}
            def contract(self, *a): return dict(contract_id='TEST261006C105000.US', underlying='TEST', right='CALL',
                expiry_date='2026-10-06', strike=105, delta=.525, bid=1, ask=1.01, quote_currency='USD',
                snapshot={'bbo_received_at': stamp.isoformat(), 'calc_received_at': stamp.isoformat()})
            def spot(self, *a): return {'last': 105, 'received_at': stamp.isoformat()}
            def scope_hash(self): return 'scope'
            def current_trend(self, original, now): return current_trend(original, args['bars'], now=now)
            def approval(self, *a): raise AssertionError('NO_QUALIFIED_APPROVAL_FOR_S1')
        for _ in range(6):
            job = jobs.claim(database, now=stamp)
            assert job
            progress, finished, revision = step(job, SyntheticTransport(), clock=lambda: stamp)
            assert jobs.settle(database, job, now=stamp, progress=progress, finished=finished, revision=revision)
    report = dict(test_only=True, market_acceptance=False, sdk_calls=0, production_writes=0,
        topology='real API/Gateway TCP threads + separate Chromium process; isolated replay DB; lifespan off',
        limitations=['not Supervisor assembly or independent backend process hour', 'no live eligibility or production approval'],
        replay=None if synthetic else str(replay), synthetic_reference=synthetic,
        frontend_hashes={str(p.relative_to(dist)): sha256(p.read_bytes()).hexdigest() for p in dist.rglob('*') if p.is_file()})
    with MonkeyPatch.context() as patch:
        for key, value in {
            'LOCALAPPDATA': str(out / 'local'), 'KQUANT_REQUIRE_API_AUTH': 'true',
            'KQUANT_API_AUTH_TOKEN': 'TEST_ONLY-browser-token', 'KQUANT_WORKSPACE_LOGIN_ENABLED': 'true',
            'KQUANT_WORKSPACE_LOGIN_EMAIL': 'test-only@example.invalid',
            'KQUANT_WORKSPACE_LOGIN_PASSWORD_HASH': generate_password_hash('TEST_ONLY_not_a_user_password'),
            'KQUANT_WORKSPACE_SESSION_SECRET': 'TEST_ONLY_SECRET' * 4,
        }.items(): patch.setenv(key, value)
        patch.delenv('KQUANT_OPTION_FOUNDATION_ROOT', raising=False)
        clock = lambda: datetime.now(UTC)
        app = create_app(config=KquantConfig(db_path=out / 'TEST_ONLY-business.sqlite3', outputs_dir=out / 'outputs'),
            research_store=database, research_clock=clock, manual_store=out / 'TEST_ONLY-manual.sqlite3')
        allowed = {'/api/alerts/stream', '/api/options/one-minute/status', '/api/options/opening-trend/current'}
        @app.middleware('http')
        async def isolate_unused(request, call_next):
            if request.url.path not in allowed and not request.url.path.startswith('/api/options/one-minute/evaluations/'):
                return JSONResponse({'detail': 'TEST_ONLY_LEGACY_NOT_MOUNTED'}, status_code=503,
                    headers={'x-kquant-test-isolation': 'legacy-not-mounted'})
            return await call_next(request)
        snapshots = app.state.research_http_snapshots
        snapshots.worker = lambda: {'session': sample['session'], 'scope_hash': sample['scope_hash']}
        snapshots.observer = lambda: {'state': 'TEST_ONLY', 'enforced': False}
        snapshots.strategy_availability = lambda s: {'enabled': s == 'opening_momentum'}
        snapshots.on_tick = None
        def load(*a, **kw):
            return store.status(path=database, session=sample['session'], scope_hash=sample['scope_hash'],
                now=clock(), policy=model.load_policy(), compact=True)
        def current(*a, **kw):
            return store.current_cards(path=database, session=sample['session'], scope_hash=sample['scope_hash'],
                now=clock(), policy=model.load_policy())
        patch.setattr('kquant.status_worker.load_opening_trend', load)
        patch.setattr('kquant.status_worker.load_current_cards', current)
        snapshots.start()
        try:
            with tcp_server(app, lifespan='off') as backend:
                gateway = create_gateway_app(stocks_url=backend, crypto_url=backend, web_dist_dir=dist,
                    stocks_api_token='TEST_ONLY-browser-token')
                with tcp_server(gateway) as url:
                    config = dict(out=str(out), url=url, target=f"{sample['symbol']} {sample['right']} S0 S1",
                        synthetic_reference=synthetic,
                        playwright_module=r'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\playwright',
                        browser_executable=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
                    config_path = out / 'browser-config.json'
                    config_path.write_text(json.dumps(config), encoding='utf-8')
                    process = subprocess.run([r'C:\Program Files\nodejs\node.exe', str(DEV / 'tools/check_browser.cjs'),
                        str(config_path)], capture_output=True, text=True, timeout=180)
                    report.update(returncode=process.returncode, stdout=process.stdout, stderr=process.stderr)
        finally:
            snapshots.close()
    (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'out': str(out), 'returncode': report.get('returncode'), 'stderr': report.get('stderr')}))
    return report.get('returncode', 1)


if __name__ == '__main__':
    raise SystemExit(main())
