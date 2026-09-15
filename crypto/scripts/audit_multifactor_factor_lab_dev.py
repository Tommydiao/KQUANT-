"""Frozen broad-factor diagnostics on TRAIN dates only; no selection or refit."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha, write_json
from kquant_crypto.hybrid_factor_experiments import diagnostics


def rank_relation(x, y):
    if len(x) < 3 or len(set(x)) < 2 or len(set(y)) < 2:
        return None
    return float(spearmanr(x, y).statistic)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dataset', required=True)
    p.add_argument('--population', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    source, population, out = [(ROOT / value).resolve() for value in (args.dataset, args.population, args.output)]
    parent = ROOT / 'outputs/hybrid_delivery'
    if any(not path.is_relative_to(parent) for path in (source, population, out)):
        raise ValueError('Independent research paths required')
    dr = json.loads((source / 'report.json').read_text())
    pr = json.loads((population / 'report.json').read_text())
    if sha(source / 'features.jsonl') != dr['features_hash'] or sha(population / 'population.jsonl') != pr['population_hash']:
        raise ValueError('Immutable input hash failure')
    out.mkdir(exist_ok=False)
    contract = {'scope': 'DEV_ONLY_TRAIN_DESCRIPTIVE', 'feature_selection': False,
        'cohorts': 'symbol,technical_mode and first/second half of TRAIN UTC dates',
        'target': '24h log-percent return, not trade netR', 'correlation_flag': .85,
        'correlation_flag_action': 'report only, never automatically add/remove factors',
        'small_group': 'n<30 is limited; larger does not establish independent evidence',
        'refit': False, 'coefficient_change': False, 'p_values': 'not reported due dependence',
        'dataset_hash': dr['features_hash'], 'population_hash': pr['population_hash'],
        'code_hash': sha(Path(__file__)), 'diagnostics_hash': sha(ROOT/'kquant_crypto/hybrid_factor_experiments.py')}
    write_json(out / 'preregistration.json', contract)
    rows = [json.loads(s) for s in (population / 'population.jsonl').read_text().splitlines()]
    train = {(r['symbol'],r['as_of']):r for r in rows if r['partition']=='TRAIN' and r['exclusion_reason'] is None}
    features = {}
    for line in (source / 'features.jsonl').read_text().splitlines():
        r = json.loads(line)
        key = r['symbol'],r['as_of']
        if key in train:
            if r['factor_contract']['factor_snapshot_hash'] != train[key]['factor_snapshot_hash']:
                raise ValueError('Per-row feature snapshot identity differs')
            features[key] = r['factor_contract']['factors']
    if set(features) != set(train):
        raise ValueError('Missing frozen TRAIN feature rows')
    keys = sorted(train, key=lambda k:(k[1],k[0]))
    names = [f['factor_id'] for f in features[keys[0]]]
    if any([f['factor_id'] for f in features[key]] != names for key in keys):
        raise ValueError('Inconsistent registered feature order')
    missing = {name:0 for name in names}
    valid = []
    for key in keys:
        bad = False
        for f in features[key]:
            if f['status'] != 'AVAILABLE' or f['value'] is None or not np.isfinite(f['value']) or f['available_at'] > key[1]:
                missing[f['factor_id']] += 1
                bad = True
        if not bad:
            valid.append(key)
    x = np.asarray([[f['value'] for f in features[key]] for key in valid], dtype=float)
    y = np.asarray([train[key]['y_log_percent'] for key in valid])
    result = diagnostics(x, y, names)
    result['high_correlation_pairs'] = [{'a':a,'b':names[j],'correlation':result['correlation'][i][j]}
        for i,a in enumerate(names) for j in range(i+1,len(names))
        if result['correlation'][i][j] is not None and abs(result['correlation'][i][j])>=.85]
    dates = sorted({key[1] for key in valid})
    midpoint = dates[len(dates)//2]
    cohorts = {'all_train':list(range(len(valid))),
               'first_train_half':[i for i,k in enumerate(valid) if k[1]<midpoint],
               'second_train_half':[i for i,k in enumerate(valid) if k[1]>=midpoint]}
    for field in ('symbol','mode'):
        for value in sorted({train[k][field] for k in valid}):
            cohorts[field+':'+value] = [i for i,k in enumerate(valid) if train[k][field]==value]
    result['cohort_rank_relations'] = {group:{'rows':len(ids),'limited':len(ids)<30,
        'feature_rank_correlation':{name:rank_relation(x[ids,j],y[ids]) for j,name in enumerate(names)}}
        for group,ids in cohorts.items()}
    result.update(scope='DEV_ONLY_TRAIN_DESCRIPTIVE', rows=len(valid), train_dates=len(dates),
        missing=missing, excluded_rows=len(keys)-len(valid), execution_enabled=False,
        independent_oos=False, probability_calibrated=False, performance='PERFORMANCE_UNPROVEN',
        automatic_selection=False)
    write_json(out/'report.json', result)
    print(json.dumps({'rows':len(valid),'registered_factors':len(names),'train_dates':len(dates),
                      'high_correlation_pairs':result['high_correlation_pairs'],'missing':missing}))


if __name__ == '__main__':
    main()
