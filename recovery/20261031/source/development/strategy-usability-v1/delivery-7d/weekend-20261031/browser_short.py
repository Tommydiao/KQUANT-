"""Real compiled UI/API/Gateway; explicit isolated TCP-thread short test, not hour."""
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import os
import importlib.util
import socket
from threading import Thread

WEEKEND=Path(__file__).resolve().parent
FIRST=WEEKEND.parent/'opening-first-hour'
os.environ['KQUANT_TEST_WEEKEND_OVERLAY']=str(WEEKEND)
spec=importlib.util.spec_from_file_location('weekend_first_hour_bootstrap',FIRST/'assembly/bootstrap.py')
boot=importlib.util.module_from_spec(spec)
spec.loader.exec_module(boot)
boot.activate()
sys.path.insert(0,str(FIRST))

from pytest import MonkeyPatch
from short_probe import prepare, inputs
from first_hour import policies
import first_hour_store as store

HERE = FIRST
ROOT = HERE.parents[4]
BASE = ROOT/'source/development/workspace'
sys.path[:0] = [str(BASE/'tests'), str(BASE/'crypto')]
from kquant.config import KquantConfig
from kquant.dashboard.app import create_app
from kquant.security import generate_password_hash
from kquant_crypto.gateway import create_gateway_app


@contextmanager
def tcp_server(app, *, lifespan='on'):
    """Same loop as dashboard/__main__.py; retain the old 2s/5s shutdown bounds."""
    import uvicorn
    sock=socket.socket()
    sock.bind(('127.0.0.1',0))
    port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan=lifespan,
        loop='asyncio:SelectorEventLoop' if sys.platform=='win32' else 'auto',
        timeout_graceful_shutdown=2))
    thread=Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True)
    thread.start()
    try:
        until=time.monotonic()+5
        while not server.started and thread.is_alive() and time.monotonic()<until:
            time.sleep(.01)
        assert server.started, 'TEST_ONLY_TCP_START_FAILED'
        yield f'http://127.0.0.1:{port}'
    finally:
        server.should_exit=True
        thread.join(5)
        sock.close()
        assert not thread.is_alive(), 'TEST_ONLY_TCP_STOP_FAILED'


def main():
    replay = '--saved-real-ai' in sys.argv
    agent_v2 = '--agent-v2' in sys.argv
    if replay and agent_v2:
        raise ValueError('CHOOSE_REAL_REPLAY_OR_SYNTHETIC_AGENT_TEST')
    out = WEEKEND/'evidence'/('browser-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    out.mkdir(parents=True)
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
        server_event_loop='asyncio:SelectorEventLoop' if sys.platform=='win32' else 'auto',
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
        from kquant import options_one_minute as common
        from kquant.options_signal_copilot import initialize_copilot_store
        from kquant.options_research_ai_store import TaskStore
        from kquant.options_research_ai_worker import captured_event
        from kquant.options_research_ai import version_identity
        ai_config=json.loads((WEEKEND/'config/research_ai.json').read_text())
        if agent_v2:
            ai_config = dict(ai_config, review_schema='research_review_v2', budget_domain='research',
                prompt_version='RESEARCH_AGENT_V2_20261101', tools_version='ASOF_LOCAL_TOOLS_V2',
                authorization_total_usd='1',
                valid_until=(args['now']+timedelta(seconds=300)).isoformat())
        patch.setattr(common,'ROOT',out)
        copilot=out/'work/options_signal_copilot/signal_copilot.sqlite3'
        initialize_copilot_store(copilot)
        child=store.detail(sample['strategy_comparison']['s1']['evaluation_id'],path)
        captured=captured_event(child,child['current_eligibility'])
        assert captured,'ELEVEN_POINT_REFERENCE_NOT_CAPTURED_FOR_AI'
        captured['_ai_versions']=version_identity(ai_config)
        (out/'TEST_ONLY-ai-event.json').write_text(json.dumps(captured,indent=2),encoding='utf-8')
        tasks=TaskStore(copilot)
        tasks.enqueue(captured,now=args['now'])
        job=tasks.claim(now=args['now'])
        assert job
        # Explicit injected failure or saved real API replay; never a new paid call.
        unavailable=dict(state='MISSING_LOCAL_KEY',delivery_state='MODEL_UNAVAILABLE',
            requested_model='gpt-6.1-sol',actual_model=None,actual_cost_usd=None,
            error_code='TEST_ONLY_MODEL_UNAVAILABLE',paid_call=False,
            versions=version_identity(ai_config),qualified_signal=False)
        if replay:
            from kquant.options_research_ai_evidence import evidence_packet, evidence_catalog
            source=WEEKEND/'evidence/real-sol-math-20261101T085741558838Z.json'
            actual=json.loads(source.read_text(encoding='utf-8'))['result']
            original=None
            for revision in range(1,6):
                event=dict(event_id='TEST_ONLY_WEEKEND_SOL_math',input_revision=revision,
                    session='TEST_ONLY',state='NUMERIC_PASS',bar_evidence=dict(open=10,high=12,low=9,close=11),
                    option_cost={'state':'UNKNOWN','cost':None},deadline_at=ai_config['valid_until'])
                if common.digest(evidence_packet(event))==actual['input_hash']:
                    original=event
                    break
            assert original is not None, 'SAVED_REAL_INPUT_IDENTITY_MISMATCH'
            unavailable={**actual,'delivery_state':'TEST_ONLY_SAVED_REAL_API_REPLAY',
                'current_opportunity':False,'qualified_signal':False,
                'replay_evidence_catalog':evidence_catalog(original),
                'replay_provenance':dict(source_file=source.name,
                    source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    original_event_id=original['event_id'],original_input_hash=actual['input_hash'],
                    original_paid_call=True,new_paid_call=False,not_this_market_event=True)}
        if agent_v2:
            from test_agent_research_v2 import review
            from test_weekend_ai import output
            from kquant.options_research_ai import ResponsesResearchClient, config_identity
            from kquant.options_research_ai_evidence import evidence_catalog
            synthetic_config = ai_config
            synthetic_receipt = dict(gate='O-SETUP', status='APPROVED', approved_by='OWNER',
                user_reply_id='TEST_ONLY_NOT_OWNER', approval_id='TEST_ONLY_V2_BROWSER',
                config_hash=config_identity(synthetic_config), budget_domain='research',
                approved_at=(args['now']-timedelta(seconds=1)).isoformat(),
                valid_until=synthetic_config['valid_until'], capability_tests_allowed=True,
                live_paid_research_allowed=False, task_limit_usd='1', authorization_total_usd='1')
            calls = []
            def synthetic_transport(request):
                calls.append(request)
                response = output(request, tool=len(calls)==1)
                if len(calls)>1:
                    response['output'][0]['content'][0]['text']=json.dumps(review())
                return response
            unavailable = ResponsesResearchClient(config=synthetic_config, receipt=synthetic_receipt,
                budget_path=out/'TEST_ONLY-agent-budget.sqlite3', transport=synthetic_transport,
                key_loader=lambda:None, clock=lambda:args['now']).assess(captured, test_only=True)
            assert unavailable['state']=='COMPLETED', unavailable
            unavailable.update(delivery_state='TEST_ONLY_SYNTHETIC_AGENT_REVIEW', current_opportunity=False,
                replay_evidence_catalog=evidence_catalog(captured, extended=True),
                replay_provenance=dict(kind='SYNTHETIC_AGENT_V2_TEST', original_paid_call=False,
                                      new_paid_call=False, not_this_market_event=True))
        tasks.finish(job,unavailable,now=args['now'])
        report['ai_state']=unavailable
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
                        ai_replay=replay, agent_v2=agent_v2,
                        playwright_module=r'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\node_modules\playwright',
                        browser_executable=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
                    config_path = out/'browser-config.json'
                    config_path.write_text(json.dumps(config), encoding='utf-8')
                    proc = subprocess.run([r'C:\Program Files\nodejs\node.exe', str(WEEKEND/'browser_short.cjs'), str(config_path)],
                                          capture_output=True, text=True, timeout=120)
                    report.update(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
        finally:
            snapshots.close()
    (out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'out':str(out), 'returncode':report.get('returncode'), 'stderr':report.get('stderr')}))
    return report.get('returncode', 1)


if __name__ == '__main__':
    raise SystemExit(main())
