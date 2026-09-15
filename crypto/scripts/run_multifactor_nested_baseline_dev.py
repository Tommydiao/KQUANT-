"""Actual nested DEV Ridge baseline; outer results never choose parameters."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha,write_json
from kquant_crypto.hybrid_factor_experiments import fit_ridge,predict
from kquant_crypto.hybrid_nested_baseline import inner_choice,ALPHAS


def main():
    p=argparse.ArgumentParser();p.add_argument('--population',required=True)
    p.add_argument('--folds',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();source,folds,out=[(ROOT/v).resolve() for v in (a.population,a.folds,a.output)]
    if any(not path.is_relative_to(ROOT/'outputs/hybrid_delivery') for path in (source,folds,out)):
        raise ValueError('Independent DEV output required')
    manifest=json.loads((folds/'fold_manifest.json').read_text())
    if manifest['version']!='opportunity_nested_dev_v1.0.1' or manifest['independent_oos']:
        raise ValueError('Corrected exposed fixed-window fold contract required')
    if sha(source/'population.jsonl')!=manifest['population_hash']:
        raise ValueError('Population differs from frozen fold membership')
    out.mkdir(exist_ok=False)
    config={'scope':'DEV_ONLY','exposure':'EXPOSED_RESEARCH','runtime_enabled':False,
        'target':'24h log-percent opportunity outcome, not trading R',
        'feature_order':['return_6h','er24','relative_volume24','relative_core24'],
        'alphas':list(ALPHAS),'criterion':'inner MSE; exact ties use declared alpha order',
        'outer_selection':False,'calibration':False,'independent_oos':False,
        'population_hash':manifest['population_hash'],'fold_hash':sha(folds/'fold_manifest.json'),
        'code_hashes':{name:sha(ROOT/name) for name in ('scripts/run_multifactor_nested_baseline_dev.py',
            'kquant_crypto/hybrid_nested_baseline.py','kquant_crypto/hybrid_factor_experiments.py')}}
    write_json(out/'preregistration.json',config)
    rows=[json.loads(s) for s in (source/'population.jsonl').read_text().splitlines()]
    index={(r['symbol'],r['as_of']):r for r in rows}
    if len(index)!=len(rows):raise ValueError('Duplicate population row')
    def arrays(keys):
        selected=[index[tuple(k)] for k in keys]
        if any(r['feature_order']!=config['feature_order'] or r['y_log_percent'] is None for r in selected):
            raise ValueError('Incomplete feature/label membership')
        return np.asarray([r['x'] for r in selected]),np.asarray([r['y_log_percent'] for r in selected])
    results=[]
    with (out/'predictions.jsonl').open('x',encoding='utf-8') as handle:
        for number,fold in enumerate(manifest['folds']):
            members=fold['membership']
            ix,iy=arrays(members['inner_train']);vx,vy=arrays(members['inner_validation'])
            choice=inner_choice(ix,iy,vx,vy)
            tx,ty=arrays(members['outer_train']);ex,ey=arrays(members['outer_diagnostic'])
            model=fit_ridge(tx,ty,choice['alpha']);prediction=predict(model,ex)
            result={'fold':number,'counts':fold['counts'],'inner_choice':choice,'model':model,
                'outer_mse':float(np.mean((ey-prediction)**2)),
                'outer_train_mean_mse':float(np.mean((ey-ty.mean())**2)),
                'outer_zero_mse':float(np.mean(ey**2)),
                'outer_start':fold['outer_start'],'outer_end':fold['outer_end']}
            results.append(result)
            for key,actual,forecast in zip(members['outer_diagnostic'],ey,prediction):
                handle.write(json.dumps({'fold':number,'symbol':key[0],'as_of':key[1],
                    'actual_log_percent':float(actual),'predicted_log_percent':float(forecast),
                    'scope':'EXPOSED_DEVELOPMENT_DIAGNOSTIC'})+'\n')
    write_json(out/'artifact.json',{**config,'folds':results})
    write_json(out/'report.json',{'scope':'DEV_ONLY','folds':results,
        'prediction_hash':sha(out/'predictions.jsonl'),'probability_calibrated':False,
        'independent_oos':False,'performance':'PERFORMANCE_UNPROVEN','runtime_enabled':False})
    print(json.dumps([{k:v for k,v in r.items() if k!='model'} for r in results]))


if __name__=='__main__':main()
