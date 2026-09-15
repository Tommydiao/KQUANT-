"""Register reviewed local deliverables, keeping partial venue work explicitly open."""
import argparse
from datetime import UTC, datetime
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_delivery import Delivery, atomic_json, load, sha


def run(output):
    out = (ROOT / output).resolve()
    if not out.is_relative_to(ROOT / 'outputs/hybrid_delivery'):
        raise ValueError('Independent checkpoint required')
    out.mkdir(parents=True, exist_ok=False)
    check = 'outputs/hybrid_delivery/checkpoint_20260906_01'
    if not load(ROOT / check / 'checkpoint.json')['engineering_regression_pass']:
        raise ValueError('Actual regression checkpoint required')
    base = check + '/baseline/audit.json'
    math = 'outputs/hybrid_delivery/posterior_review_20260906'
    mock = 'outputs/hybrid_delivery/mock_execution_20260906'
    mock_run = mock + '/protection_v1/attempt_20260905T165902Z_6f173a37'
    mc = 'outputs/hybrid_delivery/mc_history_20260906_02'
    common = [check + '/checkpoint.json', check + '/crypto_regression.log',
              check + '/isolated_math.log', check + '/preregistration.json']
    mapping = {
        'T00': [base, check + '/baseline/processes.json'],
        'T01': common + ['kquant_crypto/hybrid_delivery.py', 'tests/test_hybrid_delivery.py'],
        'T10': common + ['kquant_crypto/hybrid_quote_contract_v12.py',
                         'outputs/hybrid_delivery/w0_data_20260906_01/ticker_semantics.json'],
        'T11': common + ['kquant_crypto/hybrid_observation.py', 'kquant_crypto/hybrid_observation_slo_v12.py'],
        'T13': [base, 'outputs/hybrid_regime_v1/dev_fit_20260905_03/audit.json'],
        'T14': common + [math + '/review.json', math + '/report.md',
                         'kquant_crypto/hybrid_posterior_review.py'],
        'T15': common + [math + '/report.md',
                         'outputs/hybrid_delivery/dev_registration_20260906_01/availability.json',
                         'outputs/hybrid_delivery/dev_registration_20260906_01/clock_probes.json',
                         'outputs/hybrid_regime_v1/dev_fit_20260905_03/artifact.json',
                         'outputs/hybrid_regime_v1/dev_fit_20260905_03/baseline.json',
                         'outputs/hybrid_regime_v1/dev_fit_20260905_03/process_exit.json'],
        'T20': common + [mc + '/report.json', mc + '/input_audit.json', mc + '/preregistration.json',
                         'outputs/hybrid_delivery/mc_paths_20260906/risk_bindings.json',
                         'outputs/hybrid_delivery/mc_paths_20260906/report.md',
                         'kquant_crypto/hybrid_mc_paths_v12.py', 'kquant_crypto/hybrid_mc_history_v12.py'],
        'T30': common + [mock + '/CAPABILITY_MATRIX.md', mock_run + '/command_evidence.json',
                         'kquant_crypto/hybrid_mock_broker.py'],
        'T31': common + [mock_run + '/scenario_evidence.json', mock_run + '/command_evidence.json',
                         'kquant_crypto/hybrid_mock_oms.py'],
    }
    scopes = {
        'T14': 'Frozen posterior diagnostic review completed; no repair or support/calibration PASS. Numerical warning retained.',
        'T15': 'Existing real DEV_ONLY fit reused, baseline and current availability attested. Original creation time unknown; no backdating, G2 closed.',
        'T20': 'Synchronized path inputs and current/pending risk snapshot contract only. Actual portfolio future-risk valuation belongs to T21; G4 closed.',
        'T30': 'Credential-free synthetic broker and actual-venue UNKNOWN capability matrix; not an authenticated adapter.',
        'T31': 'Runnable Mock outbox and ambiguity/recovery lifecycle; not external exactly-once or Testnet acceptance.',
    }
    d = Delivery(ROOT)
    (out / 'receipts').mkdir()
    try:
        owners = {'T20': 'Jason:01a07036-7703-7193-924d-77b184fdfae5',
                  'T30': 'Pascal:01a07038-5ae8-7f90-9620-eecbc39961ab'}
        for tid, owner in owners.items():
            if tid in d.status()['file_ownership']:
                d.release(tid, owner)
        for tid, refs in mapping.items():
            r = {'task_id': tid, 'board_sha256': sha(d.board_path), 'status': 'VERIFIED',
                 'evidence': [{'path': p, 'sha256': sha(ROOT / p)} for p in refs],
                 'acceptance': {a: refs for a in d.tasks[tid]['acceptance']},
                 'machine_evidence': base if tid in ('T00', 'T13') else None,
                 'scope': scopes.get(tid, 'Local evidence engineering; not a trading authorization'),
                 'verified_at_raw_local_utc': datetime.now(UTC).isoformat(),
                 'G2_G11_passed': False}
            p = out / 'receipts' / (tid + '.json')
            atomic_json(p, r)
            d.record(str(p.relative_to(ROOT)))
        waiting = {
            'T12': ('WAIT_DATA', '72h SLO and natural quote-aware lifecycle not observed',
                    'Own continuous observer with predeclared time denominator and natural opportunity',
                    'outputs/hybrid_regime_v1/clock_segment_20260906_01/report.json'),
            'T17': ('WAIT_DATA', 'Zero matched QUOTE_AWARE mature labels; legacy A27 are not that target',
                    'New audited matching-target mature labels', math + '/review.json'),
            'T18': ('BLOCKED_CONTRACT', 'Timing registry registered; formal calibration/MC diagnostics and 10R interpretation still unresolved',
                    'Freeze prospective statistical contract before any final evaluation, never inspect outcomes to choose thresholds',
                    'outputs/hybrid_delivery/prospective_protocol_20260906_01/registration.json'),
        }
        for tid, (status, reason, trigger, ref) in waiting.items():
            r = {'task_id': tid, 'board_sha256': sha(d.board_path), 'status': status,
                 'evidence': [{'path': ref, 'sha256': sha(ROOT / ref)}], 'owner': 'data' if status == 'WAIT_DATA' else 'quant-contract-owner',
                 'reason': reason, 'next_trigger': trigger, 'blocked_scope': [tid]}
            p = out / 'receipts' / (tid + '.json')
            atomic_json(p, r)
            d.record(str(p.relative_to(ROOT)))
        partial = {
            'T32': 'Mock fill/cancel/fees/dust/restart verified; authenticated stream and actual account reconciliation unfinished.',
            'T33': '62-test synthetic protection suite verified; native OCO and emergency liquidation not implemented or approved.',
            'T34': 'Decimal fixture filters and deny-by-default endpoint reference checks verified; actual dynamic rules/account permissions unverified.',
        }
        progress = {'partial': partial, 'evidence': [mock_run + '/command_evidence.json',
                    mock + '/protection_v1/README.md', 'kquant_crypto/hybrid_execution_boundary_v12.py'],
                    'full_task_pass': False, 'live_enabled': False}
        progress['hashes'] = {p: sha(ROOT / p) for p in progress['evidence']}
        atomic_json(out / 'partial_work.json', progress)
        with d.db:
            d.event('PARTIAL_DELIVERY', {'path': str((out / 'partial_work.json').relative_to(ROOT)),
                                      'sha256': sha(out / 'partial_work.json'), 'tasks': list(partial)})
        d.project()
        atomic_json(out / 'state.json', d.status())
        atomic_json(out / 'live_approval_readiness.json', d.prepare_live_approval())
    finally:
        d.close()
    results = []
    for command in ('status', 'next', 'prepare-live-approval', 'evidence-report'):
        args = [sys.executable, 'scripts/run_hybrid_delivery.py', command]
        start = time.monotonic()
        proc = subprocess.run(args, cwd=ROOT, capture_output=True, timeout=90)
        (out / (command + '.log')).write_bytes(proc.stdout + proc.stderr)
        results.append({'command': args, 'exit_code': proc.returncode,
                        'elapsed_seconds': time.monotonic() - start,
                        'log_sha256': sha(out / (command + '.log'))})
        atomic_json(out / 'cli_results.json', results)
        if proc.returncode:
            raise ValueError('CLI checkpoint failed: ' + command)
    print((out / 'state.json').read_text('utf-8'))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    args = p.parse_args()
    run(args.output)
