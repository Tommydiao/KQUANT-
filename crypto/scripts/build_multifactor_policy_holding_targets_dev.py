"""New holding-label version; preserve original runs and evaluation boundaries."""
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dataset import load_development
from kquant_crypto.hybrid_dev_fit import sha, write_json
from kquant_crypto.hybrid_holding_targets_v2 import holding_target_v2


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    source, out = [(ROOT / v).resolve() for v in (args.source, args.output)]
    if any(not p.is_relative_to(ROOT / 'outputs/hybrid_delivery') for p in (source, out)):
        raise ValueError('Independent DEV paths required')
    report = json.loads((source / 'report.json').read_text())
    if report['scope'] != 'DEV_ONLY' or report['execution_enabled'] or report['independent_oos']:
        raise ValueError('Authorized exposed replay required')
    data = load_development(ROOT / 'outputs/dual_regime_v1/frozen/data_manifest.json')
    if data.content_hash != report['dataset_hash']:
        raise ValueError('Dataset differs from frozen replay')
    out.mkdir(exist_ok=False)
    policies = ['ORIGINAL', 'FIXED_2_5R', 'FIXED_3R', 'T1', 'T2']
    write_json(out / 'preregistration.json', {
        'scope': 'DEV_ONLY', 'execution_enabled': False, 'policies': policies,
        'label_available_at': 'source exit_time plus300seconds; conservative exit-bar-close proxy',
        'cost': 'BASE source ledger exit fees versus next-open5bps slip and10bps fee',
        'risk': 'immutable source base_unit_net_risk',
        'selection': 'policy-conditional holdings; not independent observations or new fills',
        'embargo': 'UNFROZEN_FOR_NEW_HOLDING_TARGET', 'training_enabled': False,
        'source_report_hash': sha(source / 'report.json'), 'dataset_hash': data.content_hash,
        'code_hashes': {name: sha(ROOT / name) for name in (
            'scripts/build_multifactor_policy_holding_targets_dev.py',
            'kquant_crypto/hybrid_holding_targets_v2.py')}})
    totals = {}
    with (out / 'holding_targets.jsonl').open('x', encoding='utf-8') as handle:
        for policy in policies:
            scenario = policy + '_1'
            path = source / scenario / 'trades.jsonl'
            if sha(path) != report['scenarios'][scenario]['trade_hash']:
                raise ValueError('Trade hash mismatch')
            trades = [json.loads(line) for line in path.read_text().splitlines()]
            counts, groups = Counter(), set()
            for trade in trades:
                bars = data.bars[trade['symbol']]['5m']
                starts = [b.start for b in bars]
                first = bisect_left(starts, trade['entry_time'])
                last = bisect_right(starts, trade['exit_time'])
                span = bars[first:last]
                complete = bool(span) and len(span) == (trade['exit_time'] - trade['entry_time']) // 300 + 1
                complete = complete and all(b.start == trade['entry_time'] + j * 300 for j, b in enumerate(span))
                for i in range(first, last):
                    if bars[i].start + 300 >= trade['exit_time']:
                        break
                    row = holding_target_v2(trade, bars[i], bars[i+1] if i+1 < len(bars) else None,
                        cutoff=data.cutoff, policy=policy, path_complete=complete)
                    row.update(symbol=trade['symbol'], mode=trade['mode'],
                        source_trade_hash=report['scenarios'][scenario]['trade_hash'])
                    handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + '\n')
                    counts[row['label_status'] + ':' + row['reason']] += 1
                    groups.add(trade['trade_id'])
            totals[policy] = {'source_trades': len(trades), 'holding_groups': len(groups), 'counts': dict(counts)}
    result = {'scope': 'DEV_ONLY', 'policies': totals, 'labels_hash': sha(out / 'holding_targets.jsonl'),
              'training_enabled': False, 'independent_oos': False, 'performance': 'PERFORMANCE_UNPROVEN'}
    write_json(out / 'report.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
