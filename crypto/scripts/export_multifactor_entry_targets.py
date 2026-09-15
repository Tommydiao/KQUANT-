"""Separate audited A-policy entry targets; never synthesize unfilled returns."""
import argparse
from bisect import bisect_right
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dev_fit import audit, CONFIG, DATA, sha, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--features', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    source = (ROOT / args.features).resolve()
    allowed = (ROOT / 'outputs/hybrid_delivery').resolve()
    if not output.is_relative_to(allowed) or not source.is_relative_to(allowed):
        raise ValueError('Independent research paths required')
    output.mkdir(exist_ok=False)
    report = json.loads((source / 'report.json').read_text())
    if sha(source / 'features.jsonl') != report['features_hash']:
        raise ValueError('Feature artifact hash mismatch')
    write_json(output / 'preregistration.json', {
        'scope': 'DEV_ONLY', 'exposure': 'EXPOSED_RESEARCH',
        'selection': 'Original A policy candidates only; not representative of all opportunities',
        'features_hash': report['features_hash'], 'source_code_hash': sha(__file__),
        'fit_enabled': False, 'runtime_enabled': False,
        'label_policy': 'LEGACY_BAR_PROXY_BASE_10_5',
        'join': 'latest completed hourly snapshot at or before signal, age strictly below one hour'})
    selected, checks = audit(json.loads(CONFIG.read_text()))
    mature = {r['label']['economic_signal_id']: r for r in selected}
    by_symbol = {}
    for line in (source / 'features.jsonl').read_text().splitlines():
        row = json.loads(line)
        by_symbol.setdefault(row['symbol'], []).append(row)
    for rows in by_symbol.values():
        rows.sort(key=lambda r: r['as_of'])
        if len({r['as_of'] for r in rows}) != len(rows):
            raise ValueError('Duplicate feature time')
    targets = []
    for line in (DATA / 'labels.jsonl').read_text().splitlines():
        label = json.loads(line)
        sid, signal = label['economic_signal_id'], label['signal_time']
        rows = by_symbol[label['symbol']]
        index = bisect_right([r['as_of'] for r in rows], signal)-1
        feature = rows[index] if index >= 0 else None
        if feature is not None and (signal-feature['as_of'] >= 3600 or feature['available_at'] > signal):
            feature = None
        executed = sid in mature
        targets.append({
            'economic_signal_id': sid, 'symbol': label['symbol'], 'mode': label['mode'],
            'signal_time': signal, 'fill_status': 'VIRTUAL_FILLED' if executed else 'UNFILLED',
            'label_status': 'MATURE' if executed else 'UNAVAILABLE_NO_FILL',
            'reason': label['reason'], 'net_r': label['net_r'] if executed else None,
            'label_available_at': label['available_at'] if executed else None,
            'exit_outcome': label['executed_trade']['exit_reason'] if executed else None,
            'base_unit_net_risk': label['executed_trade']['unit_net_risk'] if executed else None,
            'source_label_hash': label['label_hash'],
            'execution_policy_hash': label['execution_policy_hash'],
            'execution_quality': label['execution_quality'],
            'dependence_group': label.get('dependence_group'),
            'feature_snapshot': feature, 'counterfactual': False,
            'selection': 'A_POLICY_CANDIDATES', 'independent_oos': False})
    with (output / 'entry_targets.jsonl').open('x', encoding='utf-8') as handle:
        for row in targets:
            handle.write(json.dumps(row, sort_keys=True, allow_nan=False)+'\n')
    write_json(output / 'report.json', {
        'audit': checks, 'rows': len(targets), 'mature': len(mature),
        'unfilled': len(targets)-len(mature),
        'missing_hourly_features': sum(r['feature_snapshot'] is None for r in targets),
        'targets_hash': sha(output / 'entry_targets.jsonl'),
        'scope': 'DEV_ONLY', 'performance_proven': False, 'holding_targets_built': False})
    print((output / 'report.json').read_text())


if __name__ == '__main__':
    main()
