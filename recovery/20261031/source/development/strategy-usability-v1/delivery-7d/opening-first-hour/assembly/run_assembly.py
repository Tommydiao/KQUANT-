"""Existing real process assembly with the D7 delta and pending method."""
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
from contextlib import closing
import sys
from bootstrap import activate, MODULES

HERE, BASE = activate()
sys.path.insert(0, str(BASE/'scripts'))
import live_fact_topology as harness
import importlib.util
audit_spec = importlib.util.spec_from_file_location('delta_transport_audit', HERE.parent/'tools/transport_audit.py')
audit = importlib.util.module_from_spec(audit_spec)
audit_spec.loader.exec_module(audit)
from kquant.dashboard import app as app_module
actual_create_app = app_module.create_app

def create_app_with_legacy_lane(*args, **kwargs):
    if kwargs.get('research_store') is not None and kwargs.get('manual_store') is not None:
        kwargs['minute_status_store'] = kwargs['manual_store']
    return actual_create_app(*args, **kwargs)

app_module.create_app = create_app_with_legacy_lane

original_sources = harness.tested_sources
original_setup = harness.setup
original_configure = harness.configure
original_wait_initial = harness.wait_initial_snapshots
source_inventories = []
configured_out = None
from kquant.security import ApiSecurityMiddleware
original_security_dispatch = ApiSecurityMiddleware.dispatch
rate_guard_records = 0


async def observed_security_dispatch(self, request, call_next):
    global rate_guard_records
    response = await original_security_dispatch(self, request, call_next)
    if response.status_code == 429 and configured_out and rate_guard_records < 50:
        if not (configured_out/'TEST_ONLY.json').is_file():
            raise ValueError('TEST_ONLY_RATE_DIAGNOSTIC_REQUIRED')
        client = request.client.host if request.client else 'unknown'
        row = dict(test_only=True, pid=os.getpid(), request_id=request.headers.get('x-request-id'),
            path=request.url.path, status=429, monotonic=harness.monotonic(),
            configured_cap=self.settings.rate_limit_per_minute,
            actual_window_count=len(self._requests.get(client, ())),
            retry_after=response.headers.get('retry-after'),
            origin='ACTUAL_API_SECURITY_MIDDLEWARE', outcome_unchanged=True)
        with (configured_out/f'TEST_ONLY-rate-guard-{os.getpid()}.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row)+'\n')
        rate_guard_records += 1
    return response


ApiSecurityMiddleware.dispatch = observed_security_dispatch


def frozen_delta():
    selected = os.environ.get('KQUANT_TEST_FROZEN_PROJECTION')
    if not selected:
        return None
    path = Path(selected).resolve()
    if not path.is_relative_to((HERE/'release').resolve()):
        raise ValueError('TEST_PROJECTION_OUTSIDE_DELIVERY')
    raw = path.read_bytes()
    value = json.loads(raw)
    if value.get('approved') is not False or value.get('applied') is not False:
        raise ValueError('TEST_PROJECTION_NOT_UNACCEPTED')
    for row in value['changes']:
        if sha256(Path(row['payload']).read_bytes()).hexdigest() != row['sha256']:
            raise ValueError('TEST_FROZEN_PAYLOAD_CHANGED')
    return dict(test_only=True, candidate_id=value['candidate_id'],
        candidate_payload_sha256=value['candidate_payload_sha256'], projection_path=str(path),
        projection_sha256=sha256(raw).hexdigest(), changes=value['changes'],
        production_accepted=False, synthetic_transport=True)


def configure(cfg):
    global configured_out
    configured_out = Path(cfg['out'])
    frozen = os.environ.get('KQUANT_TEST_FROZEN_PROJECTION')
    weekend = os.environ.get('KQUANT_TEST_WEEKEND_OVERLAY')
    original_configure(cfg)
    if (configured_out/'TEST_ONLY.json').is_file():
        audit.install(configured_out, HERE.parents[4]/'source/evidence/new-machine-20261008')
    if frozen:
        os.environ['KQUANT_TEST_FROZEN_PROJECTION'] = frozen
    if weekend:
        os.environ['KQUANT_TEST_WEEKEND_OVERLAY'] = weekend
    os.environ['KQUANT_TEST_LEGACY_OVERLAY'] = str(HERE)
    os.environ['PYTHONPATH'] = str(Path(__file__).resolve().parent) + os.pathsep + str(BASE)
    if cfg.get('actual_assembly') and (Path(cfg['out'])/'TEST_ONLY-role-map.json').exists():
        # Import defaults only after the actual role map is installed.
        activate(verify=True)
        from kquant import options_minute_decisions
        options_minute_decisions.ROOT = Path(cfg['out'])
        mapping = {name: str(sys.modules['kquant.'+name].__file__) for name in MODULES}
        harness.write(Path(cfg['out'])/f'TEST_ONLY-loaded-modules-{os.getpid()}.json',
            dict(test_only=True, runtime_binding_installed=True, modules=mapping))


def sources():
    result = {'base/'+key: value for key, value in original_sources().items()}
    first = Path(__file__).resolve().parents[1]
    for path in sorted(first.rglob('*')):
        if path.is_file() and (path.parent == first and path.suffix == '.py' or path.parent == first/'assembly' and path.suffix in {'.py', '.cjs'} or path.is_relative_to(first/'patches')):
            result['first-hour/'+path.relative_to(first).as_posix()] = sha256(path.read_bytes()).hexdigest()
    for relative in ('start_kquant_workspace.ps1','scripts/FoundationLifecycle.ps1'):
        path=first/'lifecycle-candidate'/relative
        result['lifecycle-separate-acceptance/'+relative]=sha256(path.read_bytes()).hexdigest()
    for folder in ('patches', 'live-fact-child-tools', 'recovery-null-time-followup', 'current-card-followup', 'fact-commit-followup'):
        for path in sorted((HERE/folder).rglob('*')):
            if path.suffix in {'.py', '.json'}:
                result['delivery/'+path.relative_to(HERE).as_posix()] = sha256(path.read_bytes()).hexdigest()
    frozen = frozen_delta()
    if frozen:
        result['frozen-projection'] = frozen['projection_sha256']
    weekend=first.parent/'weekend-20261031'
    if os.environ.get('KQUANT_TEST_WEEKEND_OVERLAY')==str(weekend):
        for path in sorted(weekend.rglob('*')):
            if (path.is_file() and path.name!='EXECUTION_EVIDENCE.json'
                    and path.suffix in {'.py','.ps1','.json'} and not any(
                    part in {'evidence','C-evidence','__pycache__'} for part in path.relative_to(weekend).parts)):
                result['weekend/'+path.relative_to(weekend).as_posix()]=sha256(path.read_bytes()).hexdigest()
    source_inventories.append(result)
    return result


def wait_initial(snapshots, budget=5):
    try:
        return original_wait_initial(snapshots, budget=budget)
    except Exception:
        from kquant import status_worker
        from time import monotonic
        cache_states=[]
        for (strategy,kind),cache in snapshots.caches.items():
            cache_states.append(dict(strategy=strategy,kind=kind,cache_key=cache.cache_key,
                pending_key=cache.pending_key,has_value=cache.value is not None,ttl=cache.ttl,
                generation=cache.generation,cache_generation=cache.cache_generation,
                pending_generation=cache.pending_generation,error=cache.error,
                completed_age_seconds=monotonic()-cache.completed if cache.completed else None,
                inflight=cache.future is not None,
                future_done=cache.future.done() if cache.future is not None else None,
                pending_age_seconds=monotonic()-cache.pending_started if cache.pending_started else None))
        policy = status_worker.ROOT/'config/options_opening_momentum_v1.json'
        harness.write(configured_out/'TEST_ONLY-initial-policy-diagnostic.json', dict(test_only=True,
            pid=os.getpid(), code_root=str(status_worker.ROOT), policy_path=str(policy),
            policy_present=policy.is_file(),
            policy_sha256=sha256(policy.read_bytes()).hexdigest() if policy.is_file() else None,
            snapshot_health=snapshots.health(),cache_states=cache_states))
        raise


def setup(cfg):
    frozen = frozen_delta()
    original_setup(cfg)
    # Spawned interpreters run sitecustomize before their target's configure().
    # Install the already-created exact TEST_ONLY map before spawning any child.
    binding = Path(cfg['out'])/'TEST_ONLY-role-map.json'
    if cfg.get('actual_assembly'):
        if not binding.is_file() or not (Path(cfg['out'])/'TEST_ONLY.json').is_file():
            raise ValueError('EXACT_TEST_ONLY_BINDING_BEFORE_CHILD_REQUIRED')
        os.environ.update(KQUANT_RUNTIME_DATA_ROOT=str(Path(cfg['out'])),
            KQUANT_RUNTIME_PATH_BINDING=str(binding),
            KQUANT_RUNTIME_PATH_BINDING_SHA256=sha256(binding.read_bytes()).hexdigest())
    from kquant import options_one_minute as common
    out = Path(cfg['out'])
    for relative,source in (
            ('config/options_opening_research_ai.json',HERE/'config/research_ai.json'),
            ('config/review_acceptances/opening_ai_budget.json',HERE/'config/owner_llm_budget_sol61_20261018.json')):
        destination=out/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        with destination.open('xb') as stream:
            stream.write(source.read_bytes())
    if frozen:
        harness.write(out/'TEST_ONLY-frozen-candidate.json', frozen)
    minute = harness.minute_path(cfg)
    assert minute.is_relative_to(out)
    with closing(sqlite3.connect(minute)) as db:
        bars = [json.loads(row[0]) for row in db.execute('SELECT payload_json FROM one_minute_bars')]
    for bar in bars:
        end = common.timestamp(bar['available_at'])
        requested = (end+timedelta(milliseconds=100)).isoformat()
        bar.update(received_at=(end+timedelta(milliseconds=300)).isoformat(),
            request_started_at=requested, test_only=True,
            sdk_evidence=dict(interface='QuoteContext.candlesticks', adjustment='NoAdjust',
                provider_symbol=bar['symbol']+'.US', request_started_at=requested, test_only=True,
                clock_evidence=dict(state='VERIFIED_BOUND', uncertainty_ms=50,
                    checked_at=(end-timedelta(seconds=1)).isoformat(),
                    source_hash='TEST_ONLY_FROZEN_INPUT_ATTACHMENT', test_only=True)))
    common.save_bars(bars, cfg['session'], minute)
    if bars:
        push = deepcopy(bars[0])
        end = common.timestamp(push['available_at'])
        push['received_at'] = (end + timedelta(milliseconds=350)).isoformat()
        push['request_started_at'] = None
        push['sdk_evidence'].update(interface='QuoteContext.set_on_candlestick',
            adjustment='NOT_PROVIDED', request_started_at=None)
        common.save_bars([push], cfg['session'], minute)
        harness.write(out/'TEST_ONLY-measured-push.json', dict(test_only=True,
            native_row=push, expected='RECOVERY_PENDING_NOT_ATTRIBUTEERROR',
            original_native_pull_retained=True, production_writes=0))
    config = BASE/'config/review_acceptances/options_opening_trend_reference_sources.json'
    proof = json.loads(config.read_text())['canonical_resolution_method']
    receipt = BASE/proof['acceptance_path']
    assert sha256(receipt.read_bytes()).hexdigest() == proof['acceptance_sha256']
    destination = out/proof['acceptance_path']
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as stream:
        stream.write(receipt.read_bytes())
    reviews = json.loads((out/'TEST_ONLY-sources.json').read_text())
    reviews['canonical_resolution_method'] = proof
    harness.write(out/'TEST_ONLY-sources.json', reviews)
    harness.write(out/'TEST_ONLY-method-boundary.json', dict(test_only=True,
        genuine_method_receipt_sha256=proof['acceptance_sha256'],
        market_bars='SYNTHETIC', clock_attachments='SYNTHETIC_NOT_REAL_NTP',
        strict_source_facts='TEST_ONLY', production_launch_approval=False))
    # Exercise the same current-day cardinality that exposed production failure.
    scope = json.loads((out/'TEST_ONLY-scope.json').read_text())
    symbols = [item['symbol'] for item in scope['items'] if item['identity_status'] == 'verified']
    policy = common.load_policy()
    opening = harness.datetime.fromisoformat(cfg['opening'])
    with closing(sqlite3.connect(minute)) as db, db:
        for index in range(75900):
            symbol = symbols[index % len(symbols)]
            right = 'CALL' if index % 200 < 100 else 'PUT'
            end = opening - timedelta(minutes=1)
            payload = dict(test_only=True, evaluation_id='TEST_ONLY_HISTORY_'+str(index),
                symbol=symbol, right=right, state='INCOMPLETE', factor_evidence={},
                scope_hash=scope['scope_hash'], policy_hash=policy['policy_hash'],
                deadline_at=end.isoformat(), diagnostic_padding='TEST_ONLY_'*160)
            db.execute('INSERT INTO one_minute_evaluations VALUES (?,?,?,?,?,?,?,?,?)',
                (payload['evaluation_id'], payload['evaluation_id'], cfg['session'], symbol,
                 right, end.isoformat(), 'INCOMPLETE', json.dumps(payload), end.isoformat()))
    harness.write(out/'TEST_ONLY-legacy-lane.json', dict(test_only=True, rows=75900,
        background_lane_enabled=True, expired_synthetic_history=True, production_writes=0))


harness.configure = configure
harness.wait_initial_snapshots = wait_initial
harness.tested_sources = sources
harness.setup = setup

if __name__ == '__main__':
    try:
        raise SystemExit(harness.main())
    finally:
        if configured_out and configured_out.is_dir():
            harness.write(configured_out/'TEST_ONLY-source-inventories.json', dict(
                test_only=True, inventories=source_inventories))
            transport = audit.summarize(configured_out)
            harness.write(configured_out/'TEST_ONLY-query-accounting.json', transport)
            report_path = configured_out/'topology_report.json'
            if report_path.is_file():
                report = json.loads(report_path.read_text())
                report['legacy_included_transport_accounting'] = transport
                if not transport['complete'] or transport['totals']['failure']:
                    report.setdefault('errors', []).append(dict(code='BACKGROUND_QUERY_FAILURES',
                        failures=transport['totals']['failure'], complete=transport['complete']))
                harness.write(report_path, report)
