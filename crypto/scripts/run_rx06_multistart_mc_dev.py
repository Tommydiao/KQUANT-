"""Frozen multi-start common paths; no new signals or execution consumers."""
import argparse
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.candidate_policy import load_policy
from kquant_crypto.hybrid_conditioned_paths import conditioned_paths
from kquant_crypto.hybrid_dev_fit import sha, write_json
from kquant_crypto.hybrid_mc_paths_v12 import DevPathSpec, audit_history
from kquant_crypto.hybrid_mc_portfolio import ExistingExposurePortfolio, drawdowns
from kquant_crypto.strategy_dual_mode_v1 import Bar


def simulate(snapshot, path, policy, rules, candidates):
    ports = {c: ExistingExposurePortfolio(policy, rules, exit_candidate=c) for c in candidates}
    initial, peak, historical, maximum, maximum_historical = {}, {}, {}, {}, {}
    exits = {c: Counter() for c in candidates}
    for c, p in ports.items():
        p.restore(json.loads(json.dumps(snapshot['states'][c])))
        initial[c] = peak[c] = p.value()
        historical[c] = snapshot['historical_peaks'][c]
        if p.value() != snapshot['initial_values'][c]:
            raise ValueError('Restored value differs')
        maximum[c] = 0.
        maximum_historical[c] = (historical[c] - initial[c]) / historical[c]
    hour_rows = {s: [] for s in policy['symbols']}
    budget = {c: False for c in candidates}
    for batch in path['batches']:
        now = batch['BTCUSDT'].start + 300
        hourly = {}
        for symbol, b in batch.items():
            hour_rows[symbol].append(b)
            if now % 3600 == 0:
                seq = hour_rows[symbol]
                if len(seq) != 12 or any(b.start != seq[0].start + i*300 for i,b in enumerate(seq)):
                    raise ValueError('Incomplete generated closed hour')
                hourly[symbol] = Bar(seq[0].start, seq[0].open, max(b.high for b in seq),
                    min(b.low for b in seq), seq[-1].close, 0)
                hour_rows[symbol] = []
        for c, p in ports.items():
            p.on_path_batch(batch, hourly, now)
            result = p.drain()
            exits[c].update(t['exit_reason'] for t in result['trades'])
            dd = drawdowns(p.value(), peak[c], historical[c])
            peak[c], historical[c] = dd['starting_peak'], dd['historical_peak']
            maximum[c] = max(maximum[c], dd['incremental'])
            maximum_historical[c] = max(maximum_historical[c], dd['historical'])
            risk = sum(v.get('estimated_risk_amount', v['risk_amount'])
                for v in [*p.positions.values(), *p.pending.values()])
            budget[c] |= risk > p.value()*policy['max_open_risk'] + 1e-8
    return {c: dict(net_change=p.value()-initial[c],
        max_incremental_nav_drawdown=maximum[c], max_historical_nav_drawdown=maximum_historical[c],
        budget_exceeded=budget[c], open_at_horizon=len(p.positions), pending_at_horizon=len(p.pending),
        exit_reasons=dict(exits[c]), terminal_mark_only=True) for c,p in ports.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--starts', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--paths', type=int, choices=(2, 5000), default=5000)
    args = parser.parse_args()
    parent = ROOT/'outputs/hybrid_delivery'
    source, out = [(ROOT/p).resolve() for p in (args.starts, args.output)]
    if any(not p.is_relative_to(parent) for p in (source, out)) or out.exists():
        raise ValueError('Independent input and new output required')
    frozen = json.loads((source/'preregistration.json').read_text())
    source_report = json.loads((source/'report.json').read_text())
    config = frozen['config']
    if sha(source/'start_index.json') != source_report['index_hash']:
        raise ValueError('Start index changed')
    policy = load_policy(candidate='A')
    rules_path = ROOT/'outputs/dual_regime_v1/exchange_rules.json'
    if policy['policy_hash'] != frozen['original_policy_hash'] or sha(rules_path) != frozen['rules_hash']:
        raise ValueError('Policy/rules changed')
    rules = json.loads(rules_path.read_text())['rules']
    index = json.loads((source/'start_index.json').read_text())
    out.mkdir(exist_ok=False)
    write_json(out/'preregistration.json', dict(frozen=frozen, index_hash=source_report['index_hash'],
        requested_paths=args.paths, scope='ENGINEERING_SMOKE' if args.paths == 2 else 'DEV_ONLY_RISK',
        code_hashes={n:sha(ROOT/n) for n in ('scripts/run_rx06_multistart_mc_dev.py',
            'kquant_crypto/hybrid_mc_portfolio.py', 'kquant_crypto/hybrid_conditioned_paths.py')}))
    results = []
    for item in index:
        path = (source/item['snapshot_file']).resolve()
        if not path.is_relative_to(source) or sha(path) != item['snapshot_hash']:
            raise ValueError('Frozen snapshot changed')
        snap = json.loads(path.read_text())
        spec = DevPathSpec(snap['history'][0]['start'], snap['as_of'], snap['as_of'],
            config['block_bars'], config['horizon_bars'], args.paths, config['seed'],
            config['history_bars'], args.paths*config['horizon_bars']*3,
            snap['source_dataset_hash'], 'EXPOSED_DEV_AUTHORIZED')
        history_audit = audit_history(snap['history'], spec)
        eligible = [i for i in history_audit['eligible_block_starts']
            if snap['history'][i]['regime_before'] == snap['regime']]
        if len(eligible) < config['minimum_conditioned_blocks']:
            results.append(dict(as_of=snap['as_of'], status='UNAVAILABLE', reason='INSUFFICIENT_CONDITIONED_BLOCKS', eligible_blocks=len(eligible)))
            continue
        values = {c: [] for c in config['policies']}
        name = f"paths_{snap['as_of']}.jsonl"
        with (out/name).open('x', encoding='utf-8') as handle:
            for generated in conditioned_paths(snap['history'], snap['anchors'], spec, snap['regime']):
                result = simulate(snap, generated, policy, rules, config['policies'])
                handle.write(json.dumps(dict(path_id=generated['path_id'], sampling_hash=generated['sampling_hash'], results=result), allow_nan=False)+'\n')
                for c, value in result.items():
                    values[c].append(value)
                if (generated['path_id']+1) % 100 == 0:
                    handle.flush()
                    print(json.dumps(dict(as_of=snap['as_of'], completed=generated['path_id']+1)), flush=True)
        summary = {c:dict(net_change_quantiles=np.quantile([r['net_change'] for r in rows], [.1,.5,.9]).tolist(),
            max_historical_nav_drawdown=max(r['max_historical_nav_drawdown'] for r in rows),
            max_incremental_nav_drawdown=max(r['max_incremental_nav_drawdown'] for r in rows),
            open_at_horizon_paths=sum(r['open_at_horizon'] > 0 for r in rows)) for c,rows in values.items()}
        results.append(dict(as_of=snap['as_of'], status='SMOKE_ONLY' if args.paths == 2 else 'COMPLETED',
            paths=args.paths, summary=summary, path_hash=sha(out/name), spec=asdict(spec)))
        write_json(out/'progress.json', dict(completed_starts=len(results), total_starts=len(index)))
    report = dict(starts=results, requested_paths_per_start=args.paths, runtime_enabled=False,
        calibrated_risk=False, performance='PERFORMANCE_UNPROVEN',
        limitation='Exposed original-risk starts; correlated windows and OHLC execution proxy, no new signals, no model parameter uncertainty')
    write_json(out/'report.json', report)
    print(json.dumps(dict(starts=len(results), statuses=dict(Counter(r['status'] for r in results)), report=str(out/'report.json'))))


if __name__ == '__main__':
    main()
