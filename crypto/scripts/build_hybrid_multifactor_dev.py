"""First-stage hourly selection-independent DEV snapshot, authorized loader only."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dataset import load_development, file_hash
from kquant_crypto.hybrid_dataset_capsule import load_capsule
from kquant_crypto.hybrid_multifactor_dev import snapshot, DEFINITIONS, CROSS_DEFINITIONS, cross_section
from kquant_crypto.hybrid_multifactor_labels import opportunity_label
from kquant_crypto.hybrid_factor_contract import factor_records
from kquant_crypto.hybrid_trend_features import TrendFeatures, TREND_DEFINITIONS
from kquant_crypto.hybrid_dependence_features import dependence_snapshot, DEPENDENCE_DEFINITIONS


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    p.add_argument('--capsule', help='Authorized DEV-only portable dataset directory')
    a = p.parse_args()
    out = (ROOT/a.output).resolve()
    if not out.is_relative_to(ROOT/'outputs/hybrid_delivery'):
        raise ValueError('Independent output required')
    out.mkdir(parents=True, exist_ok=False)
    manifest = ROOT/'outputs/dual_regime_v1/frozen/data_manifest.json'
    capsule = (ROOT/a.capsule).resolve() if a.capsule else None
    registration = {'scope':'DEV_ONLY', 'exposure':'EXPOSED_RESEARCH',
                    'sampling':'every proven closed 1h, independent of old fills/signals',
                    'features':DEFINITIONS, 'cross_section_features':CROSS_DEFINITIONS,
                    'trend_features':TREND_DEFINITIONS,
                    'dependence_features':DEPENDENCE_DEFINITIONS,
                    'code_hashes': {name:file_hash(ROOT/name) for name in (
                        'scripts/build_hybrid_multifactor_dev.py',
                        'kquant_crypto/hybrid_multifactor_dev.py',
                        'kquant_crypto/hybrid_multifactor_labels.py',
                        'kquant_crypto/hybrid_factor_contract.py',
                        'kquant_crypto/hybrid_trend_features.py',
                        'kquant_crypto/hybrid_dependence_features.py',
                        'kquant_crypto/strategy_dual_mode_v1.py',
                        'kquant_crypto/hybrid_dataset.py',
                        'kquant_crypto/hybrid_dataset_capsule.py')},
                    'fit':False, 'source_manifest_hash':file_hash(manifest) if capsule is None else None,
                    'capsule_manifest_hash':file_hash(capsule/'capsule.json') if capsule else None,
                    'missing_forward_only':['spread','depth','slippage','CVD','trade_count','OI'],
                    'labels':{'horizons_hours':[6,24], 'reference':'signal closed-hour close',
                              'scope':'gross descriptive return/MFE/MAE, not strategy net R',
                              'terminal_policy':'censored null, never zero or fabricated fill',
                              'holding_exit_policy_unchanged':True}, 'execution_enabled':False}
    (out/'preregistration.json').write_text(json.dumps(registration), encoding='utf-8')
    data = load_capsule(capsule) if capsule else load_development(manifest)
    indexed = {}
    histories = {}
    for symbol, frames in data.bars.items():
        hours = frames['1h']
        histories[symbol] = {bar.start+3600: hours[max(0,i-24):i+1] for i, bar in enumerate(hours)}
        indexed[symbol] = {bar.start+3600: snapshot(hours[max(0,i-24):i+1], bar.start+3600)
                           for i, bar in enumerate(hours)}
    counts = Counter()
    cross_counts = Counter()
    label_counts = Counter()
    with (out/'features.jsonl').open('x', encoding='utf-8') as f, \
            (out/'opportunity_labels.jsonl').open('x', encoding='utf-8') as labels:
        for symbol, frames in data.bars.items():
            rows = frames['1h']
            starts = [b.start for b in rows]
            trend = TrendFeatures()
            for i, bar in enumerate(rows):
                as_of = bar.start+3600
                trend_row = trend.update(bar,as_of)
                if as_of <= data.manifest['window']['start']:
                    continue
                row = snapshot(rows[max(0,i-24):i+1], as_of)
                row.update(symbol=symbol, source=data.manifest['source'],
                           dataset_hash=data.content_hash, as_of=as_of,
                           available_at=as_of, availability_basis='assumed_close_historical_replay')
                row['cross_section'] = cross_section(
                    {s: snapshots[as_of] for s, snapshots in indexed.items() if as_of in snapshots},
                    symbol, as_of)
                cross_counts[row['cross_section']['status']] += 1
                row['trend'] = trend_row
                row['dependence'] = dependence_snapshot(
                    {s: h[as_of] for s,h in histories.items() if as_of in h}, symbol, as_of)
                row['factor_contract'] = factor_records(row)
                counts[symbol+':'+row['status']] += 1
                f.write(json.dumps(row, sort_keys=True, allow_nan=False)+'\n')
                for horizon in (6,24):
                    label = opportunity_label(rows,starts,as_of,bar.close,horizon,data.cutoff)
                    label.update(symbol=symbol, dataset_hash=data.content_hash,
                                 availability_basis='assumed_close_historical_replay')
                    label_counts[str(horizon)+':'+label['label_status']] += 1
                    labels.write(json.dumps(label,sort_keys=True,allow_nan=False)+'\n')
    if any(file_hash(ROOT/name) != digest for name, digest in registration['code_hashes'].items()):
        raise RuntimeError('Source changed during dataset build; output must not be consumed')
    report = dict(registration, counts=dict(counts), cross_section_counts=dict(cross_counts), cutoff=data.cutoff,
                  dataset_hash=data.content_hash, features_hash=file_hash(out/'features.jsonl'),
                  label_counts=dict(label_counts), label_rows=sum(label_counts.values()),
                  labels_hash=file_hash(out/'opportunity_labels.jsonl'),
                  entry_net_r_labels_built=False, holding_labels_built=False,
                  model_trained=False, performance_proven=False)
    (out/'report.json').write_text(json.dumps(report,sort_keys=True),encoding='utf-8')
    print(json.dumps(report))
