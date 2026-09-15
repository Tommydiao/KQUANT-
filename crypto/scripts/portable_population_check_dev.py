"""Explicit saved-posterior replay capsule; never fits or enables a model."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import tempfile
import zipfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build(out):
    root = Path(__file__).resolve().parents[1]
    base = root/'outputs/hybrid_delivery'
    model = base/'multifactor_population_fit_20260908_01'
    paths = {name: model/name for name in ('posterior.nc','artifact.json','preprocessing.json','training_rows.json','diagnostics.json','preregistration.json')}
    paths.update({'population.jsonl':base/'multifactor_population_20260907_01/population.jsonl',
        'expected_predictions.jsonl':base/'multifactor_population_prediction_20260908_01/predictions.jsonl',
        'portable_population_check_dev.py':Path(__file__)})
    payload = {name:path.read_bytes() for name,path in paths.items()}
    versions = {name:importlib.metadata.version(name) for name in ('numpy','scipy','arviz','xarray','h5netcdf','h5py')}
    manifest = dict(scope='DEV_ONLY_SAVED_POSTERIOR_REPLAY', execution_enabled=False,
        files={name:sha(data) for name,data in payload.items()}, dependency_versions=versions,
        python=sys.version, calibrated=False, independent_oos=False,
        limitations=['Not a training replay or full project release','No raw OHLC history or MC paths included',
                     'Failed numerical model retained; gross log returns not net trade R'],
        command='python portable_population_check_dev.py verify --archive <capsule.zip> --output <new-directory>')
    out.mkdir(parents=True,exist_ok=False)
    archive = out/'saved_population_replay.zip'
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED) as z:
        for name,data in sorted(payload.items()):
            z.writestr(name,data)
        z.writestr('MANIFEST.json',json.dumps(manifest,indent=2))
    if any(sha(path.read_bytes()) != manifest['files'][name] for name,path in paths.items()):
        raise ValueError('Source changed while packaging')
    (out/'package.json').write_text(json.dumps(dict(archive_sha256=sha(archive.read_bytes()),
        archive_bytes=archive.stat().st_size, manifest=manifest),indent=2),encoding='utf-8')
    return dict(archive=str(archive),archive_sha256=sha(archive.read_bytes()))


def verify(archive,out):
    if out.exists(): raise FileExistsError(out)
    import numpy as np
    import xarray as xr
    from scipy.stats import t
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        if len(names)!=len(set(names)): raise ValueError('Duplicate archive entries')
        manifest=json.loads(z.read('MANIFEST.json'))
        if set(names)!=set(manifest['files'])|{'MANIFEST.json'}: raise ValueError('Unexpected archive entries')
        payload={name:z.read(name) for name in manifest['files']}
    if any(sha(data)!=manifest['files'][name] for name,data in payload.items()): raise ValueError('Capsule hash mismatch')
    if manifest['execution_enabled'] is not False: raise ValueError('Invalid capsule scope')
    versions={name:importlib.metadata.version(name) for name in manifest['dependency_versions']}
    if versions!=manifest['dependency_versions']: raise ValueError('Dependency version mismatch')
    meta=json.loads(payload['artifact.json']);prep=json.loads(payload['preprocessing.json'])
    if meta['scope']!='DEV_ONLY' or meta['runtime_enabled'] is not False: raise ValueError('Model permission mismatch')
    if sha(payload['posterior.nc'])!=meta['posterior_sha256'] or sha(payload['population.jsonl'])!=meta['population_hash']:
        raise ValueError('Model provenance mismatch')
    rows=[json.loads(s) for s in payload['population.jsonl'].splitlines()]
    train=[r for r in rows if r['partition']=='TRAIN' and r['exclusion_reason'] is None]
    evaluate=[r for r in rows if r['partition']=='DEVELOPMENT_DIAGNOSTIC' and r['exclusion_reason'] is None]
    expected=[json.loads(s) for s in payload['expected_predictions.jsonl'].splitlines()]
    if train!=json.loads(payload['training_rows.json']) or len(evaluate)!=len(expected): raise ValueError('Row identity mismatch')
    xt=np.asarray([r['x'] for r in train]);std=xt.std(axis=0);std=np.where(std>1e-12,std,1.)
    groups=sorted({r['symbol']+':'+r['mode'] for r in train})
    if not np.array_equal(xt.mean(axis=0),prep['mean']) or not np.array_equal(std,prep['std']) or groups!=prep['groups']:
        raise ValueError('TRAIN-only transform mismatch')
    if any(r['feature_order']!=meta['feature_order'] for r in train+evaluate): raise ValueError('Feature order mismatch')
    with tempfile.TemporaryDirectory(prefix='kquant_saved_posterior_') as tmp:
        path=Path(tmp)/'posterior.nc';path.write_bytes(payload['posterior.nc'])
        with xr.open_dataset(path,group='posterior',engine='h5netcdf') as dataset:
            posterior=dataset.load()
        with xr.open_dataset(path,group='sample_stats',engine='h5netcdf') as stats:
            divergence_count=int(stats.diverging.sum())
        if posterior.sizes['chain']!=meta['chains'] or posterior.sizes['draw']!=meta['draws']:
            raise ValueError('Posterior dimensions mismatch')
        if list(posterior.coords['feature'].values)!=meta['feature_order'] or list(posterior.coords['group'].values)!=groups:
            raise ValueError('Posterior coordinates mismatch')
        post=posterior.stack(sample=('chain','draw'))
        alpha=np.asarray(post.alpha.transpose('sample'));beta=np.asarray(post.beta.transpose('sample','feature'))
        tau=np.asarray(post.tau.transpose('sample'));z=np.asarray(post.z.transpose('sample','group'))
        sigma=np.asarray(post.sigma.transpose('sample'));nu=2+np.asarray(post.nu_minus_two.transpose('sample'))
        x=(np.asarray([r['x'] for r in evaluate])-prep['mean'])/std
        idx=[groups.index(r['symbol']+':'+r['mode']) for r in evaluate]
        mu=alpha[:,None]+beta@x.T+tau[:,None]*z[:,idx]
        probability=np.mean(t.sf(-mu/sigma[:,None],df=nu[:,None]),axis=0)
        rng=np.random.default_rng(202609077)
        q=np.quantile(mu+sigma[:,None]*rng.standard_t(nu[:,None],size=mu.shape),[.05,.5,.95],axis=0)
        prediction=mu.mean(axis=0)
    errors=[]
    for i,(row,saved) in enumerate(zip(evaluate,expected)):
        if any(row[k]!=saved[k] for k in ('symbol','mode','as_of')): raise ValueError('Forecast identity mismatch')
        actual=[prediction[i],probability[i],*q[:,i]]
        original=[saved['expected_log_percent'],saved['positive_gross_probability_uncalibrated'],*saved['log_percent_quantiles05_50_95']]
        if not np.allclose(actual,original,rtol=1e-10,atol=1e-10): raise ValueError('Saved forecast replay mismatch')
        errors.append(float(np.max(np.abs(np.asarray(actual)-original))))
    if divergence_count!=meta['diagnostics']['divergences']: raise ValueError('Divergence count mismatch')
    result=dict(status='SAVED_POSTERIOR_REPLAY_PASS',rows=len(evaluate),training_rows=len(train),
        max_absolute_difference=max(errors),divergences=divergence_count,versions=versions,
        numerical_gate='FAIL' if divergence_count else 'NOT_REASSESSED',trained=False,
        runtime_enabled=False,calibrated=False,performance='PERFORMANCE_UNPROVEN',
        archive_sha256=sha(archive.read_bytes()),self_code_hash=sha(Path(__file__).read_bytes()))
    out.mkdir(parents=True,exist_ok=False)
    (out/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=('build','verify'))
    p.add_argument('--output',required=True);p.add_argument('--archive')
    args=p.parse_args()
    result=build(Path(args.output).resolve()) if args.action=='build' else verify(Path(args.archive).resolve(),Path(args.output).resolve())
    print(json.dumps(result),flush=True)
