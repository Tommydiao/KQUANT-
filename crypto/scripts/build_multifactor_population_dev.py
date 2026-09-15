"""Selection-independent daily opportunity population, not executed trade labels."""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dataset import load_development
from kquant_crypto.hybrid_dev_fit import sha, write_json
from kquant_crypto.strategy_dual_mode_v1 import DualRegimeKernel

FEATURES = ['return_6h', 'er24', 'relative_volume24', 'relative_core24']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    source, out = (ROOT / args.dataset).resolve(), (ROOT / args.output).resolve()
    parent = ROOT / 'outputs/hybrid_delivery'
    if not source.is_relative_to(parent) or not out.is_relative_to(parent):
        raise ValueError('Independent DEV paths required')
    report = json.loads((source / 'report.json').read_text())
    if report['scope'] != 'DEV_ONLY' or report['exposure'] != 'EXPOSED_RESEARCH':
        raise ValueError('Authorized exposed research required')
    for file, key in [('features.jsonl', 'features_hash'), ('opportunity_labels.jsonl', 'labels_hash')]:
        if sha(source / file) != report[key]:
            raise ValueError('Dataset hash mismatch')
    out.mkdir(exist_ok=False)
    write_json(out / 'preregistration.json', {
        'version': 'population_logreturn_dev_v1', 'scope': 'DEV_ONLY',
        'selection': 'every UTC midnight in authorized DEV; independent of signal/virtual fill',
        'label': '100*log(1+24h gross_return), not plan netR or trade profit',
        'mode': 'frozen A technical kernel, entries suppressed, no portfolio-exit feedback',
        'states': 'UP_TREND/RANGE/TRANSITION; TRANSITION does not grant trading permission',
        'split': 'first60% of authorized DEV dates for training, remainder exposed diagnostic only',
        'purge_embargo': 'training label available strictly before development boundary minus24h',
        'cross_asset_dependence': 'same UTC date retained as dependency group, not independent observations',
        'feature_order': FEATURES, 'execution_enabled': False, 'independent_oos': False,
        'source_report_hash': sha(source / 'report.json'), 'code_hash': sha(Path(__file__)),
        'kernel_hash': sha(ROOT / 'kquant_crypto/strategy_dual_mode_v1.py')})
    data = load_development(ROOT / 'outputs/dual_regime_v1/frozen/data_manifest.json')
    if data.content_hash != report['dataset_hash']:
        raise ValueError('Historical dataset identity differs')
    start, end = data.manifest['window']['start'], data.cutoff
    boundary = start + int(((end - start) // 86400) * .6) * 86400
    modes = {}
    for symbol, frames in data.bars.items():
        kernel = DualRegimeKernel('A')
        hours = {b.start + 3600: b for b in frames['1h']}
        for bar in frames['5m']:
            stamp = bar.start + 300
            decision = kernel.on_bar(bar, hours.get(stamp), allow_entries=False)
            if stamp % 86400 == 0 and start < stamp <= end:
                modes[symbol, stamp] = {'mode': decision['mode'], 'ready': decision['ready']}
    labels = {}
    for line in (source / 'opportunity_labels.jsonl').read_text().splitlines():
        r = json.loads(line)
        if r['horizon_hours'] == 24 and r['signal_time'] % 86400 == 0:
            key = r['symbol'], r['signal_time']
            if key in labels:
                raise ValueError('Duplicate daily label')
            labels[key] = r
    counts = Counter()
    rows = []
    for line in (source / 'features.jsonl').read_text().splitlines():
        f = json.loads(line)
        key = f['symbol'], f['as_of']
        if f['as_of'] % 86400:
            continue
        label = labels[key]
        state = modes[key]
        values = {**f['values'], **f['cross_section']['values']}
        x = [values[k] for k in FEATURES]
        reason = None
        if label['label_status'] != 'MATURE':
            reason = label['label_status']
        elif not state['ready'] or any(v is None or not math.isfinite(v) for v in x):
            reason = 'MISSING_FEATURE_OR_WARMUP'
        elif label['gross_return'] <= -1:
            reason = 'INVALID_LOG_RETURN_SUPPORT'
        partition = 'DEVELOPMENT_DIAGNOSTIC'
        if f['as_of'] < boundary:
            partition = 'TRAIN'
            if label['label_available_at'] is not None and label['label_available_at'] >= boundary - 86400:
                reason = reason or 'PURGED_EMBARGO'
        row = {'symbol': f['symbol'], 'mode': state['mode'], 'as_of': f['as_of'],
               'available_at': f['available_at'], 'label_available_at': label['label_available_at'],
               'dependency_group': f['as_of'] // 86400, 'partition': partition,
               'exclusion_reason': reason, 'feature_order': FEATURES, 'x': x,
               'y_log_percent': 100 * math.log1p(label['gross_return']) if reason is None else None,
               'factor_snapshot_hash': f['factor_contract']['factor_snapshot_hash'],
               'fill_status': 'NOT_APPLICABLE', 'label_status': label['label_status'],
               'execution_quality': label['execution_quality'], 'exposure': 'EXPOSED_RESEARCH'}
        rows.append(row)
        counts[partition + ':' + (reason or 'ELIGIBLE')] += 1
    rows.sort(key=lambda r: (r['as_of'], r['symbol']))
    with (out / 'population.jsonl').open('x', encoding='utf-8') as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + '\n')
    result = {'scope': 'DEV_ONLY', 'counts': dict(counts), 'rows': len(rows),
              'boundary': boundary, 'authorized_cutoff': end, 'dataset_hash': data.content_hash,
              'population_hash': sha(out / 'population.jsonl'),
              'mode_counts': dict(Counter(r['mode'] for r in rows if r['exclusion_reason'] is None)),
              'execution_enabled': False, 'independent_oos': False,
              'performance': 'PERFORMANCE_UNPROVEN', 'model_trained': False}
    write_json(out / 'report.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
