"""Freeze outcome-blind historical MC starts; no paths, network or execution."""
import argparse
from collections import deque
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.candidate_policy import load_policy, digest
from kquant_crypto.hybrid_dataset_capsule import load_capsule
from kquant_crypto.hybrid_dev_fit import sha, write_json
from kquant_crypto.hybrid_mc_start_selection import select_starts
from kquant_crypto.hybrid_research_portfolio import ResearchPortfolio


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    parent = ROOT / 'outputs/hybrid_delivery'
    out = (ROOT / args.output).resolve()
    if not out.is_relative_to(parent) or out.exists():
        raise ValueError('New isolated output required')
    config_path = ROOT / 'config/rx06_multistart_dev_v1.json'
    config = json.loads(config_path.read_text())
    capsule = parent / 'multifactor_dataset_capsule_20260909_01'
    data = load_capsule(capsule)
    policy = load_policy(candidate='A')
    rules_path = ROOT / 'outputs/dual_regime_v1/exchange_rules.json'
    rules = json.loads(rules_path.read_text())['rules']
    portfolios = {c: ResearchPortfolio(policy, rules, exit_candidate=c) for c in config['policies']}
    peaks = {c: p.value() for c, p in portfolios.items()}
    out.mkdir(exist_ok=False)
    write_json(out / 'preregistration.json', dict(config=config, config_hash=sha(config_path),
        capsule_manifest_hash=sha(capsule / 'capsule.json'), dataset_hash=data.content_hash,
        original_policy_hash=policy['policy_hash'], rules_hash=sha(rules_path),
        code_hashes={name: sha(ROOT/name) for name in (
            'scripts/freeze_rx06_multistarts_dev.py', 'kquant_crypto/hybrid_mc_start_selection.py',
            'kquant_crypto/candidate_simulation.py', 'kquant_crypto/hybrid_research_portfolio.py',
            'kquant_crypto/hybrid_exit_research.py', 'kquant_crypto/strategy_dual_mode_v1.py')}))
    timeline, hours = {}, {}
    for symbol, frames in data.bars.items():
        for b in frames['5m']:
            timeline.setdefault(b.start, {})[symbol] = b
        for b in frames['1h']:
            hours.setdefault(b.start + 3600, {})[symbol] = b
    history = deque(maxlen=config['history_bars'])
    metadata, starts, seen = [], [], set()
    for start, bars in sorted(timeline.items()):
        now = start + 300
        history.append({'start': start, 'regime_before': portfolios['ORIGINAL'].kernels['BTCUSDT'].mode,
            'bars': {s: {**asdict(b), 'available_at': now, 'source_bar_id': f'{s}:{start}'}
                     for s, b in bars.items()}})
        for candidate, portfolio in portfolios.items():
            portfolio.on_closed_batch(bars, hours.get(now, {}), now,
                allow_entries=now >= data.manifest['window']['start'])
            portfolio.drain()
            peaks[candidate] = max(peaks[candidate], portfolio.value())
        if now % 3600 or now < data.manifest['window']['start']:
            continue
        original = portfolios['ORIGINAL']
        hist = list(history)
        row = dict(as_of=now, regime=original.kernels['BTCUSDT'].mode,
            nav=original.value(), historical_peak=peaks['ORIGINAL'],
            original_positions=len(original.positions), original_pending=len(original.pending),
            history_bars=len(hist), history_end=hist[-1]['start'] + 300,
            history_contiguous=all(b['start'] == hist[0]['start'] + i * 300
                and set(b['bars']) == set(policy['symbols']) for i, b in enumerate(hist)))
        metadata.append(row)
        if row['regime'] not in config['regimes']:
            raise ValueError('Unregistered snapshot regime')
        choice = select_starts([row])['selected']
        if not choice or tuple(choice[0]['selection_key']) in seen:
            continue
        seen.add(tuple(choice[0]['selection_key']))
        states = {c: p.snapshot() for c, p in portfolios.items()}
        for c, state in states.items():
            restored = ResearchPortfolio(policy, rules, exit_candidate=c)
            restored.restore(json.loads(json.dumps(state)))
            if digest(restored.snapshot()) != digest(state) or restored.value() != portfolios[c].value():
                raise ValueError('Snapshot restore parity failed')
        snapshot = dict(as_of=now, selection=choice[0], states=states,
            historical_peaks=dict(peaks), initial_values={c:p.value() for c,p in portfolios.items()},
            anchors=dict(original.marks), history=hist, regime=row['regime'],
            availability_contract='LEGACY_BAR_PROXY_ASSUMED_CLOSE_NOT_HISTORICAL_RECEIPT',
            data_cutoff=data.cutoff, source_dataset_hash=data.content_hash,
            config_hash=sha(config_path), no_future_rows=True, paths_generated=0)
        name = f'start_{now}.json'
        write_json(out/name, snapshot)
        starts.append(dict(as_of=now, selection_key=choice[0]['selection_key'],
            snapshot_file=name, snapshot_hash=sha(out/name),
            policy_positions={c:len(p.positions) for c,p in portfolios.items()},
            policy_pending={c:len(p.pending) for c,p in portfolios.items()}))
    audit = select_starts(metadata)
    if [r['as_of'] for r in audit['selected']] != [r['as_of'] for r in starts]:
        raise ValueError('Streaming selection differs from full outcome-blind audit')
    write_json(out/'start_index.json', starts)
    write_json(out/'hourly_selection_audit.json', dict(rows=metadata, audit=audit))
    report = dict(scope='DEV_ONLY_EXPOSED_RISK_RESEARCH', starts=len(starts),
        hourly_rows=len(metadata), index_hash=sha(out/'start_index.json'),
        audit_hash=sha(out/'hourly_selection_audit.json'), restore_parity=True,
        paths_generated=0, runtime_enabled=False, calibrated_risk=False,
        performance='PERFORMANCE_UNPROVEN', dataset_hash=data.content_hash,
        limitation='Independent portfolio states; original-exposure conditioned start population, not all candidate-only positions or full-strategy performance')
    write_json(out/'report.json', report)
    print(json.dumps(report))


if __name__ == '__main__':
    main()
