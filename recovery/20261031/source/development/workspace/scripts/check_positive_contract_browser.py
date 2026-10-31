"""Bounded TEST_ONLY qualification queue -> API/Gateway -> compiled browser probe.

No production lifecycle, SDK, business data, or genuine OWNER approval is used.
The calendar clock has a fixed offset and advances at wall speed. A single
synthetic quote is generated after browser readiness and never renewed.
"""
import argparse
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
import traceback
from time import monotonic, sleep, time

CODE = Path(__file__).resolve().parents[1]
SOURCE = CODE.parents[1]
sys.path.insert(0, str(CODE))
sys.path.insert(0, str(CODE / 'tests'))
sys.path.insert(0, str(CODE / 'crypto'))

from pytest import MonkeyPatch
from fastapi.responses import JSONResponse
from test_positive_contract_tcp import tcp_server
from test_r58_positive_chain import prepare
from kquant.config import KquantConfig
from kquant.dashboard.app import create_app
from kquant.security import generate_password_hash
from kquant import options_one_minute as common
from kquant import options_opening_momentum as model
from kquant import options_opening_trend_store as store
from kquant import options_opening_trend_jobs as jobs
from kquant import options_opening_trend_approval as approvals
from kquant import options_release_acceptance as release
from kquant.options_opening_trend_pipeline import step
from kquant_crypto.gateway import create_gateway_app


def write(path, value):
    path.write_text(json.dumps(value, indent=2, default=str), encoding='utf-8')


def bind_test_release(out, dist, strategy_path, patch):
    front = {str(p.relative_to(SOURCE)).replace('\\', '/'): sha256(p.read_bytes()).hexdigest()
             for p in sorted(dist.rglob('*')) if p.is_file()}
    assert front and (dist / 'unified.html').is_file(), 'COMPILED_UNIFIED_ENTRY_MISSING'
    runtime_files = {str(p.relative_to(SOURCE)).replace('\\', '/'): sha256(p.read_bytes()).hexdigest()
                     for folder in (CODE / 'kquant', CODE / 'crypto/kquant_crypto')
                     for p in sorted(folder.rglob('*.py'))}
    source_hash = common.digest({'test_only': True, 'scope': 'SYNTHETIC_BROWSER_BRIDGE',
                                 'fixture_fact_sha256': sha256((strategy_path.parent / 'test-fact.txt').read_bytes()).hexdigest(),
                                 'policy_hash': model.load_policy()['policy_hash']})
    manifest = out / 'TEST_ONLY-release.json'
    write(manifest, {'test_only': True, 'frontend': str(dist.relative_to(SOURCE)),
                     'frontend_files': front, 'runtime_files': runtime_files, 'source_contract_policy_hash': source_hash})
    digest = sha256(manifest.read_bytes()).hexdigest()
    bundle = {'test_only': True, 'runtime_manifest_sha256': digest, 'source_contract_policy_hash': source_hash}
    bundle['bundle_sha256'] = common.digest(bundle)
    bundle_path = out / 'TEST_ONLY-bundle.json'
    write(bundle_path, bundle)
    record = {'test_only': True, 'status': 'APPROVED', 'approved_by': 'OWNER',
              'runtime_manifest_sha256': digest, 'frontend_files_hash': common.digest(front),
              'bundle_path': str(bundle_path.relative_to(SOURCE)), 'bundle_sha256': bundle['bundle_sha256'],
              'source_contract_policy_hash': source_hash}
    environment = {'KQUANT_RUNTIME_MANIFEST': str(manifest), 'KQUANT_BACKEND_MANIFEST_SHA256': digest,
                   'KQUANT_BACKEND_RELEASE_ID': out.name, 'KQUANT_GATEWAY_WEB_DIST': str(dist)}
    verifier = release.verify
    patch.setattr(release, 'verify', lambda value: verifier(value, root=SOURCE, environment=environment))
    strategy = json.loads(strategy_path.read_bytes())
    strategy['release_acceptance'] = record
    write(strategy_path, strategy)
    result = approvals.status(model.load_policy(), 'scope')
    assert result['qualified_signal_pipeline_enabled'], result
    assert result['release_acceptance']['status'] == 'PASS', result
    write(out / 'TEST_ONLY-acceptance-check.json', result)
    return front, runtime_files


def run(cli):
    out = Path(cli.out).resolve()
    assert out.is_relative_to(SOURCE / 'evidence'), 'ISOLATED_EVIDENCE_ROOT_REQUIRED'
    out.mkdir(parents=True, exist_ok=False)
    dist = CODE / 'web/dist-unified'
    report = {'test_only': True, 'market_acceptance': False, 'production_started': False, 'errors': [],
              'topology': 'isolated TCP server threads and separate actual browser process',
              'limitations': ['synthetic sources', 'isolated store snapshot loader', 'production lifespan off',
                              'not final independent-process hour', 'not natural market signal']}
    process = None
    snapshots = None
    with MonkeyPatch.context() as patch:
        try:
            fixture = out / 'fixture'
            fixture.mkdir()
            args, original, services, strategy_path = prepare(fixture, patch)
            offset_ms = round(args['now'].timestamp() * 1000 - time() * 1000)
            clock = lambda: datetime.now(UTC) + timedelta(milliseconds=offset_ms)
            report['clock_offset_ms'] = offset_ms
            report['frontend_files'], report['runtime_files'] = bind_test_release(out, dist, strategy_path, patch)
            for key, value in {
                'LOCALAPPDATA': str(out / 'local'), 'KQUANT_REQUIRE_API_AUTH': 'true',
                'KQUANT_API_AUTH_TOKEN': 'TEST_ONLY-browser-token', 'KQUANT_WORKSPACE_LOGIN_ENABLED': 'true',
                'KQUANT_WORKSPACE_LOGIN_EMAIL': 'test-only@example.invalid',
                'KQUANT_WORKSPACE_LOGIN_PASSWORD_HASH': generate_password_hash('TEST_ONLY_not_a_user_password'),
                'KQUANT_WORKSPACE_SESSION_SECRET': 'TEST_ONLY_SECRET' * 4,
            }.items(): patch.setenv(key, value)
            patch.delenv('KQUANT_OPTION_FOUNDATION_ROOT', raising=False)
            database = out / 'TEST_ONLY-research.sqlite3'
            store.initialize(database)
            if cli.mode.startswith('manual'):
                common.initialize(out / 'manual.sqlite3')
            app = create_app(config=KquantConfig(db_path=out / 'business.sqlite3', outputs_dir=out / 'outputs'),
                             research_store=database, research_clock=clock, manual_store=out / 'manual.sqlite3')
            detail_path = '/api/options/one-minute/evaluations/' + original['evaluation_id']
            allowed = {'/api/alerts/stream', '/api/options/one-minute/status', '/api/options/opening-trend/current', detail_path}
            if cli.mode.startswith('manual'):
                allowed.update({'/api/options/one-minute/manual', '/api/options/one-minute/manual/entries',
                                '/api/options/one-minute/manual/exits'})
            report['manual_response_faults'] = []
            @app.middleware('http')
            async def isolate_unused(request, call_next):
                if request.url.path not in allowed:
                    return JSONResponse({'detail': 'TEST_ONLY_LEGACY_NOT_MOUNTED'}, status_code=503,
                                        headers={'x-kquant-test-isolation': 'legacy-not-mounted'})
                response = await call_next(request)
                if (cli.mode == 'manual-response-loss' and request.method == 'POST'
                        and request.url.path in {'/api/options/one-minute/manual/entries', '/api/options/one-minute/manual/exits'}
                        and response.status_code == 200
                        and not any(f['path'] == request.url.path for f in report['manual_response_faults'])):
                    # The real route committed. Deliberately lose its success response once.
                    report['manual_response_faults'].append({'test_only': True, 'phase': 'AFTER_COMMIT', 'path': request.url.path,
                                                            'wall_ms': time() * 1000})
                    await response.body_iterator.aclose()
                    return JSONResponse({'detail': 'TEST_ONLY_COMMITTED_RESPONSE_LOST'}, status_code=503)
                return response
            snapshots = app.state.research_http_snapshots
            from kquant.options_price_action_source import observation_summary
            source_observation = observation_summary({'TEST': {
                'state': 'CAPABILITY_BLOCKED', 'received_at': clock().isoformat(),
                'requested_coverage_from': '2026-10-01', 'requested_coverage_through': '2026-10-02',
                'actual_query': None, 'reasons': ['TEST_ONLY_DATED_INTERFACE_UNAVAILABLE']}})
            source_observation['coverage_counts'] = {'fresh': 0, 'expired': 1, 'deferred': 0}
            snapshots.worker = lambda: {'session': original['session'], 'scope_hash': 'scope',
                'price_action_sources': deepcopy(source_observation),
                'source_request_budget': {'used': 0, 'local_cap': 12, 'provider_limit_verified': False},
                'source_call': {'in_flight': False}}
            snapshots.observer = lambda: {'state': 'TEST_ONLY', 'enforced': False}
            snapshots.strategy_availability = lambda s: {'enabled': s == 'opening_momentum'}
            snapshots.on_tick = None
            def load(*args, **unused):
                kwargs = dict(path=database, session=original['session'], scope_hash='scope', now=clock(), policy=model.load_policy())
                return store.status(**kwargs, compact=True)
            def load_current(*args, **unused):
                return store.current_cards(path=database, session=original['session'], scope_hash='scope',
                                           now=clock(), policy=model.load_policy())
            # Keep the real API projection; only substitute isolated store selection.
            patch.setattr('kquant.status_worker.load_opening_trend', load)
            patch.setattr('kquant.status_worker.load_current_cards', load_current)
            snapshots.start()
            with tcp_server(app, lifespan='off') as backend:
                gateway = create_gateway_app(stocks_url=backend, crypto_url=backend, web_dist_dir=dist,
                                             stocks_api_token='TEST_ONLY-browser-token')
                with tcp_server(gateway) as url:
                    config = {'out': str(out), 'url': url, 'clock_offset_ms': offset_ms,
                              'playwright_module': cli.playwright_module, 'browser_executable': cli.browser_executable,
                              'mode': cli.mode, 'evaluation_id': original['evaluation_id'],
                              'original_deadline': original['deadline_at']}
                    write(out / 'browser-config.json', config)
                    with (out / 'browser-stdout.txt').open('w') as stdout, (out / 'browser-stderr.txt').open('w') as stderr:
                        process = subprocess.Popen([cli.node, str(CODE / 'scripts/check_positive_contract_browser.cjs'),
                                                    str(out / 'browser-config.json')], stdout=stdout, stderr=stderr)
                        limit = monotonic() + 45
                        while not (out / 'browser-ready.json').exists() and process.poll() is None and monotonic() < limit:
                            if (out / 'browser-source-ready.json').exists() and not report.get('source_revision_changed'):
                                source_observation['recent_observations'][0]['reasons'] = ['TEST_ONLY_SOURCE_REVISION_SEEN']
                                source_observation['observation_revision'] = 'TEST_ONLY-revision-two'
                                report['source_revision_changed'] = True
                            sleep(.05)
                        assert (out / 'browser-ready.json').exists(), 'BROWSER_NOT_READY'
                        # Generate exactly one new synthetic price observation, after readiness.
                        receipt = clock().isoformat()
                        contract = deepcopy(services.contract('TEST261006C105000.US'))
                        contract['snapshot'].update(bbo_received_at=receipt, calc_received_at=receipt,
                                                    test_only_observation_id='ONE_SYNTHETIC_ARRIVAL')
                        services.contract = lambda *a: deepcopy(contract)
                        services.spot = lambda *a: {'symbol': 'TEST', 'last': 105, 'received_at': receipt}
                        report['quote_generated_wall_ms'] = time() * 1000
                        report['quote_received_at'] = receipt
                        store.persist([original], database)
                        for _ in range(12):
                            job = jobs.claim(database, now=clock())
                            assert job, 'QUALIFICATION_JOB_MISSING'
                            progress, finished, revision = step(job, services, clock=clock)
                            outcome = jobs.settle(database, job, now=clock(), progress=progress, finished=finished,
                                                  revision=revision, return_revision=True)
                            assert outcome['committed']
                            if outcome['revision']:
                                committed = outcome['revision']
                                report['revision'] = committed
                                assert committed['state'] == 'QUALIFIED', committed
                                report['qualified_wall_ms'] = time() * 1000
                                report['evaluation_id'] = original['evaluation_id']
                                report['original_deadline'] = original['deadline_at']
                                app.state.alert_hub.publish({'type': 'options_one_minute_eligibility',
                                    'research_strategy': 'opening_momentum', 'evaluation_id': original['evaluation_id'],
                                    'revision': committed, 'qualified_signal': True})
                                break
                        assert report.get('qualified_wall_ms'), 'NO_QUALIFIED_COMMIT'
                        if cli.mode == 'structure':
                            limit = monotonic() + 8
                            while not (out / 'browser-rendered.json').exists() and process.poll() is None and monotonic() < limit:
                                sleep(.01)
                            assert (out / 'browser-rendered.json').exists(), 'NO_RENDER_BEFORE_INVALIDATION'
                            # A new underlying observation invalidates structure; the BBO is not refreshed.
                            invalid_spot = {'symbol': 'TEST', 'last': original['structure_line'] - .1,
                                            'received_at': clock().isoformat()}
                            services.spot = lambda *a: dict(invalid_spot)
                            report['invalidating_spot'] = invalid_spot
                            for _ in range(6):
                                job = jobs.claim(database, now=clock())
                                assert job, 'REFRESH_JOB_MISSING'
                                progress, finished, revision = step(job, services, clock=clock)
                                outcome = jobs.settle(database, job, now=clock(), progress=progress, finished=finished,
                                                      revision=revision, return_revision=True)
                                assert outcome['committed']
                                if outcome['revision']:
                                    withdrawn = outcome['revision']
                                    assert withdrawn['state'] == 'WITHDRAWN', withdrawn
                                    assert 'PRICE_OR_TREND_INVALIDATED' in withdrawn['reasons'], withdrawn
                                    report['withdrawal'] = withdrawn
                                    report['withdrawal_wall_ms'] = time() * 1000
                                    app.state.alert_hub.publish({'type': 'options_one_minute_eligibility',
                                        'research_strategy': 'opening_momentum', 'evaluation_id': original['evaluation_id'],
                                        'revision': withdrawn, 'qualified_signal': False})
                                    break
                            assert report.get('withdrawal'), 'WITHDRAWAL_NOT_COMMITTED'
                            store.persist([original], database)
                            assert jobs.claim(database, now=clock()) is None, 'TERMINAL_JOB_REOPENED'
                        elif cli.mode == 'deadline':
                            deadline = common.timestamp(original['deadline_at'])
                            assert (deadline - common.timestamp(original['calculation_bar_end'])).total_seconds() == 300
                            limit = monotonic() + 310
                            while clock() < deadline and process.poll() is None and monotonic() < limit:
                                write(out / 'deadline-progress.json', {'test_only': True, 'observed_at': clock(),
                                      'original_deadline': original['deadline_at'], 'remaining_seconds': (deadline-clock()).total_seconds()})
                                sleep(min(1, max(.01, (deadline-clock()).total_seconds())))
                            assert clock() >= deadline, 'FULL_ORIGINAL_DEADLINE_NOT_OBSERVED'
                            assert jobs.claim(database, now=clock()) is None
                            expired = store.detail(original['evaluation_id'], database)
                            assert expired['deadline_at'] == original['deadline_at']
                            assert expired['current_eligibility']['state'] == 'EXPIRED', expired
                            report['expired_revision'] = expired['current_eligibility']
                            report['deadline_observed_wall_ms'] = time() * 1000
                            write(out / 'deadline-processed.json', {'test_only': True, 'evaluation_id': original['evaluation_id']})
                        process.wait(timeout=120 if cli.mode.startswith('manual') else 25)
                        report['browser_exit_code'] = process.returncode
                        assert process.returncode == 0, 'BROWSER_POSITIVE_CHECK_FAILED'
                        browser = json.loads((out / 'browser-result.json').read_bytes())
                        report['browser'] = browser
                        if cli.mode.startswith('manual'):
                            entry = browser['manual']['entry']
                            assert entry['strategy_hash'] == original['policy_hash']
                            assert entry['policy_snapshot'] == original['policy_snapshot']
                            assert entry['trigger_low'] == original['bar_evidence']['low']
                            assert entry['trigger_high'] == original['bar_evidence']['high']
                            assert browser['manual']['session_revoked_and_restored']
                            if cli.mode == 'manual-response-loss':
                                assert len(report['manual_response_faults']) == 2
                                assert browser['manual']['ui_retry_reconciled_without_post']
                                assert browser['manual']['exit_retry_reconciled_without_post']
                        assert browser['current_cards'], 'NO_BROWSER_CURRENT_PAYLOAD'
                        for card in browser['current_cards']:
                            assert card['evaluation_id'] == original['evaluation_id']
                            assert card['deadline_at'] == original['deadline_at']
                            assert card['contract_id'] == 'TEST261006C105000.US'
                        assert len({card['valid_until'] for card in browser['current_cards']}) == 1, 'QUOTE_WAS_RENEWED'
                        expiry_wall_ms = common.timestamp(browser['current_cards'][0]['valid_until']).timestamp() * 1000 - offset_ms
                        assert browser['first_render_wall_ms'] < expiry_wall_ms, 'RENDERED_AFTER_QUOTE_EXPIRY'
                        report['quote_expiry_wall_ms'] = expiry_wall_ms
                        report['observed_removal_after_expiry_ms'] = browser['removed_wall_ms'] - expiry_wall_ms
                        report['qualification_to_observed_render_ms'] = browser['first_render_wall_ms'] - report['qualified_wall_ms']
                        report['frontend_hashes_unchanged'] = all(sha256((SOURCE / p).read_bytes()).hexdigest() == h
                                                               for p, h in report['frontend_files'].items())
                        assert report['frontend_hashes_unchanged']
                        report['runtime_hashes_unchanged'] = all(sha256((SOURCE / p).read_bytes()).hexdigest() == h
                                                               for p, h in report['runtime_files'].items())
                        assert report['runtime_hashes_unchanged']
                        if cli.mode in ('disconnect', 'structure'):
                            assert browser['removed_wall_ms'] < expiry_wall_ms, 'EARLY_REMOVAL_NOT_BEFORE_EXPIRY'
                        if cli.mode == 'structure':
                            report['withdrawal_to_observed_removal_ms'] = browser['removed_wall_ms'] - report['withdrawal_wall_ms']
                        report['browser_positive_bridge'] = True
        except Exception as exc:
            report['errors'].append(f'{type(exc).__name__}: {exc}')
            report['traceback'] = traceback.format_exc()
        finally:
            if process and process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            if snapshots:
                snapshots.close()
            report['probe_passed'] = not report['errors'] and report.get('browser_positive_bridge', False)
            write(out / 'result.json', report)
    print(json.dumps({'test_only': True, 'out': str(out), 'errors': report['errors'],
                      'browser_positive_bridge': report.get('browser_positive_bridge', False)}))
    return 1 if report['errors'] else 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for option in ('out', 'node', 'playwright-module', 'browser-executable'):
        parser.add_argument('--' + option, required=True)
    parser.add_argument('--mode', choices=('quote-expiry', 'disconnect', 'structure', 'deadline', 'manual', 'manual-response-loss'), default='quote-expiry')
    raise SystemExit(run(parser.parse_args()))
