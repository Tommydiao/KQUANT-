"""Frozen exposed diagnostic check, not calibration or independent OOS."""
import argparse
import json
from pathlib import Path
import sys
import numpy as np
from scipy.stats import t as student_t

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha, write_json
from kquant_crypto.hybrid_multifactor_artifact import inspect_artifact
from kquant_crypto.hybrid_prediction_diagnostics import diagnostic_breakdown


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--artifact', required=True)
    p.add_argument('--population', required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    model, population, out = [(ROOT/value).resolve() for value in (args.artifact,args.population,args.output)]
    parent = ROOT/'outputs/hybrid_delivery'
    if any(not path.is_relative_to(parent) for path in (model,population,out)):
        raise ValueError('Independent research paths required')
    meta = inspect_artifact(model, purpose='DEV_ONLY')
    if meta['version'] != 'population_student_t_dev_v1' or meta['diagnostics']['status'] != 'COMPLETED':
        raise ValueError('Completed registered population artifact required')
    if sha(population/'population.jsonl') != meta['population_hash']:
        raise ValueError('Population differs from training contract')
    out.mkdir(exist_ok=False)
    write_json(out/'diagnostic_contract.json', {'scope':'EXPOSED_DEVELOPMENT_DIAGNOSTIC',
        'fit_or_recalibration':False,'selection':False,'predictive_seed':202609077,
        'direction_target':'positive gross24h return, NOT costed plan profitability',
        'metrics':['log-percent MAE/RMSE','positive-gross Brier','10 equal-width ECE bins','central90% predictive coverage'],
        'baselines':['training mean log-return','training positive fraction','zero log-return'],
        'paired_error_bootstrap':{'seed':202609078,'replicates':2000,'block_days':7,
            'unit':'UTC date with all assets together','minimum_stable_nonoverlapping_blocks':12,
            'scope':'exposed descriptive error comparison, not calibration or profit gate'},
        'grouped_diagnostic_code_hash':sha(ROOT/'kquant_crypto/hybrid_prediction_diagnostics.py'),
        'independent_oos':False,'probability_calibrated':False,'runtime_enabled':False,
        'code_hash':sha(Path(__file__)),'posterior_hash':meta['posterior_sha256']})
    rows = [json.loads(s) for s in (population/'population.jsonl').read_text().splitlines()]
    train = [r for r in rows if r['partition']=='TRAIN' and r['exclusion_reason'] is None]
    evaluate = [r for r in rows if r['partition']=='DEVELOPMENT_DIAGNOSTIC' and r['exclusion_reason'] is None]
    if json.loads((model/'training_rows.json').read_text()) != train:
        raise ValueError('Training row provenance changed')
    prep = json.loads((model/'preprocessing.json').read_text())
    xt = np.asarray([r['x'] for r in train]); yt=np.asarray([r['y_log_percent'] for r in train])
    std=xt.std(axis=0); std=np.where(std>1e-12,std,1.)
    groups=sorted({r['symbol']+':'+r['mode'] for r in train})
    if not np.array_equal(prep['mean'],xt.mean(axis=0)) or not np.array_equal(prep['std'],std) or prep['groups']!=groups:
        raise ValueError('Preprocessing not derived only from frozen training rows')
    if prep['feature_order'] != meta['feature_order'] or any(r['feature_order'] != meta['feature_order'] for r in evaluate):
        raise ValueError('Feature order changed')
    if any(r['symbol']+':'+r['mode'] not in groups for r in evaluate):
        raise ValueError('Unseen group requires abstention, not guessed intercept')
    import arviz as az
    trace=az.from_netcdf(model/'posterior.nc')
    if trace.posterior.sizes.get('chain')!=meta['chains'] or trace.posterior.sizes.get('draw')!=meta['draws']:
        raise ValueError('Incomplete chain/draw dimensions cannot be a completed fit')
    if list(trace.posterior.coords['feature'].values)!=meta['feature_order'] or list(trace.posterior.coords['group'].values)!=groups:
        raise ValueError('Posterior feature/group order differs from preprocessing')
    post=trace.posterior.stack(sample=('chain','draw'))
    alpha=np.asarray(post.alpha.transpose('sample'))
    beta=np.asarray(post.beta.transpose('sample','feature'))
    tau=np.asarray(post.tau.transpose('sample'))
    z=np.asarray(post.z.transpose('sample','group'))
    sigma=np.asarray(post.sigma.transpose('sample'))
    nu=2+np.asarray(post.nu_minus_two.transpose('sample'))
    x=(np.asarray([r['x'] for r in evaluate])-prep['mean'])/std
    y=np.asarray([r['y_log_percent'] for r in evaluate])
    idx=[groups.index(r['symbol']+':'+r['mode']) for r in evaluate]
    mu=alpha[:,None]+beta@x.T+tau[:,None]*z[:,idx]
    probability=np.mean(student_t.sf(-mu/sigma[:,None],df=nu[:,None]),axis=0)
    rng=np.random.default_rng(202609077)
    predictive=mu+sigma[:,None]*rng.standard_t(nu[:,None],size=mu.shape)
    quantiles=np.quantile(predictive,[.05,.5,.95],axis=0)
    prediction=mu.mean(axis=0)
    actual=(y>0).astype(float); prior_frequency=float(np.mean(yt>0))
    bins=[]
    membership=np.minimum((probability*10).astype(int),9)
    for i in range(10):
        selected=membership==i
        bins.append({'lower':i/10,'upper':(i+1)/10,'count':int(selected.sum()),
                     'mean_probability':float(probability[selected].mean()) if selected.any() else None,
                     'observed_positive_fraction':float(actual[selected].mean()) if selected.any() else None})
    result={'scope':'DEV_ONLY','rows':len(evaluate),'dependency_dates':len({r['dependency_group'] for r in evaluate}),
        'mean_log_percent_mae':float(np.mean(abs(y-prediction))),
        'train_mean_mae':float(np.mean(abs(y-yt.mean()))),
        'rmse_log_percent':float(np.sqrt(np.mean((y-prediction)**2))),
        'zero_rmse':float(np.sqrt(np.mean(y*y))),
        'positive_gross_brier':float(np.mean((probability-actual)**2)),
        'train_frequency_brier':float(np.mean((prior_frequency-actual)**2)),
        'ece':sum(b['count']/len(y)*abs(b['mean_probability']-b['observed_positive_fraction']) for b in bins if b['count']),
        'central90_predictive_coverage':float(np.mean((y>=quantiles[0])&(y<=quantiles[2]))),
        'reliability_bins':bins,'probability_calibrated':False,'independent_oos':False,
        'performance':'PERFORMANCE_UNPROVEN','runtime_enabled':False,
        'limits':'One exposed development segment; correlated assets, no test selection, no costs or execution performance implied'}
    with (out/'predictions.jsonl').open('x',encoding='utf-8') as handle:
        for i,row in enumerate(evaluate):
            handle.write(json.dumps({'symbol':row['symbol'],'mode':row['mode'],'as_of':row['as_of'],
                'actual_log_percent':float(y[i]),'expected_log_percent':float(prediction[i]),
                'positive_gross_probability_uncalibrated':float(probability[i]),
                'log_percent_quantiles05_50_95':quantiles[:,i].tolist(),'scope':'DEV_ONLY'},allow_nan=False)+'\n')
    result['prediction_hash']=sha(out/'predictions.jsonl')
    breakdown = diagnostic_breakdown(evaluate, prediction, probability, quantiles[0], quantiles[2],
        training_mean=float(yt.mean()), training_positive_fraction=prior_frequency)
    write_json(out/'grouped_diagnostics.json', breakdown)
    result['grouped_diagnostics_hash'] = sha(out/'grouped_diagnostics.json')
    result['grouped_diagnostic_code_hash'] = sha(ROOT/'kquant_crypto/hybrid_prediction_diagnostics.py')
    write_json(out/'report.json',result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
