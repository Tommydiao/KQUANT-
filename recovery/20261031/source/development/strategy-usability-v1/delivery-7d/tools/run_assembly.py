"""Existing real process assembly with the D7 delta and pending method."""
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
import check_r58_p10_topology as harness

original_sources = harness.tested_sources
original_setup = harness.setup
original_configure = harness.configure
original_wait_initial = harness.wait_initial_snapshots
source_inventories = []
configured_out = None


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
    original_configure(cfg)
    if (configured_out/'TEST_ONLY.json').is_file():
        from transport_audit import install
        install(configured_out, HERE.parents[2]/'evidence/new-machine-20261008')
    if frozen:
        os.environ['KQUANT_TEST_FROZEN_PROJECTION'] = frozen
    os.environ['KQUANT_TEST_D7_OVERLAY'] = str(HERE)
    os.environ['PYTHONPATH'] = str(HERE/'tools') + os.pathsep + str(BASE)
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
    for folder in ('patches', 'tools'):
        for path in sorted((HERE/folder).rglob('*')):
            if path.suffix in {'.py', '.json'}:
                result['delivery/'+path.relative_to(HERE).as_posix()] = sha256(path.read_bytes()).hexdigest()
    frozen = frozen_delta()
    if frozen:
        result['frozen-projection'] = frozen['projection_sha256']
    source_inventories.append(result)
    return result


def wait_initial(snapshots, budget=5):
    try:
        return original_wait_initial(snapshots, budget=budget)
    except Exception:
        from kquant import status_worker
        policy = status_worker.ROOT/'config/options_opening_momentum_v1.json'
        harness.write(configured_out/'TEST_ONLY-initial-policy-diagnostic.json', dict(test_only=True,
            pid=os.getpid(), code_root=str(status_worker.ROOT), policy_path=str(policy),
            policy_present=policy.is_file(),
            policy_sha256=sha256(policy.read_bytes()).hexdigest() if policy.is_file() else None,
            snapshot_health=snapshots.health()))
        raise


def setup(cfg):
    frozen = frozen_delta()
    original_setup(cfg)
    from kquant import options_one_minute as common
    out = Path(cfg['out'])
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
    config = HERE/'patches/config/review_acceptances/options_opening_trend_reference_sources.json'
    proof = json.loads(config.read_text())['canonical_resolution_method']
    receipt = HERE/'patches'/proof['acceptance_path']
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
