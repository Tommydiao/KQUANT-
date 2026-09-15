"""Fixed exposed-research rolling regression; no strategy admission consumer."""
import argparse
import json
from pathlib import Path
import sys
import hashlib
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_factor_experiments import fit_ridge, predict, diagnostics
FEATURES = ['return_6h', 'er24', 'relative_volume24', 'relative_core24']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False), encoding='utf-8')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dataset', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    source, out = (ROOT/args.dataset).resolve(), (ROOT/args.output).resolve()
    parent = ROOT/'outputs/hybrid_delivery'
    if not source.is_relative_to(parent) or not out.is_relative_to(parent):
        raise ValueError('Independent research directories required')
    out.mkdir(exist_ok=False)
    report = json.loads((source/'report.json').read_text())
    for name, key in [('features.jsonl','features_hash'), ('opportunity_labels.jsonl','labels_hash')]:
        if digest(source/name) != report[key]:
            raise ValueError('Dataset integrity failure')
    config = {'scope':'DEV_ONLY', 'exposure':'EXPOSED_RESEARCH', 'independent_oos':False,
              'feature_order':FEATURES, 'horizon_hours':24, 'ridge_alpha':1.0,
              'split':'three expanding chronological folds:40-60,60-80,80-100 percent',
              'purge':'label available strictly before evaluation start minus24h',
              'missing':'exclude missing rows, no imputation', 'preprocessing':'training mean/std only',
              'targets':'gross descriptive24h returns, not trade netR',
              'selection':'fixed features, no parameter search', 'execution_enabled':False,
              'dataset_report_hash':digest(source/'report.json'), 'code_hash':digest(Path(__file__)),
              'experiment_code_hash':digest(ROOT/'kquant_crypto/hybrid_factor_experiments.py'),
              'diagnostics':'training-only quintiles/correlation; fixed leave-one-feature-out, no reselection',
              'command':sys.argv, 'interpreter':sys.executable, 'numpy_version':np.__version__}
    dump(out/'preregistration.json', config)
    labels = {}
    for line in (source/'opportunity_labels.jsonl').read_text().splitlines():
        r = json.loads(line)
        if r['horizon_hours'] == 24 and r['label_status'] == 'MATURE':
            key = (r['symbol'],r['signal_time'])
            if key in labels:
                raise ValueError('Duplicate label')
            labels[key] = r
    rows = []
    for line in (source/'features.jsonl').read_text().splitlines():
        r = json.loads(line)
        label = labels.get((r['symbol'],r['as_of']))
        values = dict(r['values'], **r['cross_section']['values'])
        x = [values.get(k) for k in FEATURES]
        if label and all(v is not None and np.isfinite(v) for v in x):
            rows.append((r['as_of'],r['symbol'],x,label['gross_return'],label['label_available_at']))
    rows.sort(key=lambda r:(r[0],r[1]))
    times = sorted({r[0] for r in rows})
    if len(times)<100:
        raise ValueError('Insufficient calendar history')
    x = np.asarray([r[2] for r in rows]); y = np.asarray([r[3] for r in rows])
    t = np.asarray([r[0] for r in rows]); available = np.asarray([r[4] for r in rows])
    results = []
    with (out/'predictions.jsonl').open('x',encoding='utf-8') as handle:
        for fold,(lo,hi) in enumerate(((.4,.6),(.6,.8),(.8,1.0))):
            start = times[int(len(times)*lo)]
            end = times[int(len(times)*hi)] if hi<1 else times[-1]+3600
            train = available < start-86400
            evaluate = (t>=start)&(t<end)
            model = fit_ridge(x[train],y[train])
            prediction = predict(model,x[evaluate])
            intercept = model['intercept']
            actual = y[evaluate]
            result = {'fold':fold,'evaluation_start':start,'evaluation_end':end,
                      'train_rows':int(train.sum()),'evaluation_rows':int(evaluate.sum()),
                      'max_train_label_available':int(available[train].max()),
                      'mean':model['mean'],'std':model['std'],'coefficient':model['coefficient'],
                      'intercept':intercept,
                      'mse_zero':float(np.mean(actual**2)),
                      'mse_train_mean':float(np.mean((actual-intercept)**2)),
                      'mse_ridge':float(np.mean((actual-prediction)**2))}
            result['train_diagnostics'] = diagnostics(x[train],y[train],FEATURES)
            result['ablation_mse'] = {}
            for j,name in enumerate(FEATURES):
                keep = [k for k in range(len(FEATURES)) if k!=j]
                reduced = fit_ridge(x[train][:,keep],y[train])
                result['ablation_mse'][name] = float(np.mean((actual-predict(reduced,x[evaluate][:,keep]))**2))
            assert result['max_train_label_available'] < start-86400
            results.append(result)
            for idx, pred in zip(np.flatnonzero(evaluate),prediction):
                handle.write(json.dumps({'fold':fold,'symbol':rows[idx][1],'as_of':int(t[idx]),
                    'actual_gross_return':float(y[idx]),'prediction':float(pred)},allow_nan=False)+'\n')
    dump(out/'artifact.json',dict(config,folds=results,runtime_enabled=False))
    dump(out/'report.json',{'folds':results,'scope':'DEV_ONLY','performance':'PERFORMANCE_UNPROVEN',
        'overlap_limit':'24h labels overlap within evaluation and across assets; no iid confidence claims',
        'probability_calibrated':False,'prediction_hash':digest(out/'predictions.jsonl')})
    print(json.dumps(results))


if __name__ == '__main__':
    main()
