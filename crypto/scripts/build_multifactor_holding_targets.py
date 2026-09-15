"""Export exposed, original-policy conditional holding comparisons."""
import argparse
from bisect import bisect_left
from collections import Counter
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dataset import load_development
from kquant_crypto.hybrid_dev_fit import audit, CONFIG, sha, write_json
from kquant_crypto.hybrid_holding_targets import holding_target


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    out = (ROOT/p.parse_args().output).resolve()
    if not out.is_relative_to(ROOT/'outputs/hybrid_delivery'):
        raise ValueError('Independent output required')
    out.mkdir(exist_ok=False)
    write_json(out/'preregistration.json', {
        'scope': 'DEV_ONLY_EXPOSED_RESEARCH', 'execution_enabled': False,
        'selection': 'All proven closed 5m observations within original A27 holdings',
        'comparison': 'Original realized policy exit vs next open sell with original 5bps slip and 10bps fee',
        'independent_samples': False, 'risk_denominator': 'original frozen BASE unit risk',
        'limitation': 'Conditional old-policy holding sample; not T1/T2 rollout or independent OOS',
        'source_hashes': {name:sha(ROOT/name) for name in (
            'scripts/build_multifactor_holding_targets.py',
            'kquant_crypto/hybrid_holding_targets.py')}})
    selected, checks = audit(json.loads(CONFIG.read_text()))
    data = load_development(ROOT/'outputs/dual_regime_v1/frozen/data_manifest.json')
    counts = Counter()
    groups = Counter()
    with (out/'holding_targets.jsonl').open('x', encoding='utf-8') as handle:
        for record in selected:
            label = record['label']
            trade = label['executed_trade']
            bars = data.bars[label['symbol']]['5m']
            starts = [b.start for b in bars]
            i = bisect_left(starts, trade['entry_time'])
            while i < len(bars) and bars[i].start+300 < trade['exit_time']:
                bar = bars[i]
                row = holding_target(trade, bar, bars[i+1] if i+1 < len(bars) else None,
                                     cutoff=data.cutoff)
                row.update(symbol=label['symbol'], mode=label['mode'],
                           source_label_hash=label['label_hash'], dataset_hash=data.content_hash,
                           availability_basis='assumed_close_historical_replay')
                handle.write(json.dumps(row, sort_keys=True, allow_nan=False)+'\n')
                counts[row['label_status']] += 1
                groups[trade['trade_id']] += 1
                i += 1
    result = {'counts': dict(counts), 'holding_groups': dict(groups),
              'source_trades': len(selected), 'groups_with_observations': len(groups),
              'source_audit': checks, 'dataset_hash': data.content_hash,
              'targets_hash': sha(out/'holding_targets.jsonl'),
              'scope': 'DEV_ONLY', 'performance_proven': False}
    write_json(out/'report.json', result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('source_audit','holding_groups')}))


if __name__ == '__main__':
    main()
