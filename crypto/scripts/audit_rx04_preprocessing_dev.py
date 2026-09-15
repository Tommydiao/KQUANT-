"""Audit the frozen population preprocessing, without importing a model runtime."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha, write_json


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    base=ROOT/'outputs/hybrid_delivery'
    out=(ROOT/args.output).resolve()
    if not out.is_relative_to(base) or out.exists():
        raise ValueError('New isolated evidence directory required')
    model=base/'multifactor_population_fit_20260908_01'
    population=base/'multifactor_population_20260907_01'
    paths=[population/'population.jsonl',population/'report.json',model/'artifact.json',
           model/'training_rows.json',model/'preprocessing.json',model/'preregistration.json']
    hashes={str(p.relative_to(ROOT)):sha(p) for p in paths}
    rows=[json.loads(s) for s in paths[0].read_text().splitlines()]
    source=json.loads(paths[1].read_text());meta=json.loads(paths[2].read_text())
    prep=json.loads(paths[4].read_text());policy=json.loads(paths[5].read_text())
    if sha(paths[0])!=meta['population_hash']:
        raise ValueError('Population identity mismatch')
    train=[r for r in rows if r['partition']=='TRAIN' and r['exclusion_reason'] is None]
    diagnostic=[r for r in rows if r['partition']=='DEVELOPMENT_DIAGNOSTIC' and r['exclusion_reason'] is None]
    if train!=json.loads(paths[3].read_text()) or not train or not diagnostic:
        raise ValueError('Training provenance mismatch')
    if len({(r['symbol'],r['as_of']) for r in rows})!=len(rows):
        raise ValueError('Duplicate population snapshot')
    for r in train+diagnostic:
        if (r['available_at']>r['as_of'] or r['label_available_at']<=r['as_of'] or
            r['feature_order']!=policy['feature_order'] or r['exposure']!='EXPOSED_RESEARCH' or
            r['fill_status']!='NOT_APPLICABLE' or r['label_status']!='MATURE' or
            not np.isfinite(r['x']).all() or not np.isfinite(r['y_log_percent'])):
            raise ValueError('Time/feature/target eligibility failure')
    if max(r['label_available_at'] for r in train)>=source['boundary']-86400:
        raise ValueError('Frozen training purge contract violated')
    x=np.asarray([r['x'] for r in train]);std=x.std(axis=0)
    std=np.where(std>1e-12,std,1.)
    groups=sorted({r['symbol']+':'+r['mode'] for r in train})
    if (not np.array_equal(x.mean(axis=0),prep['mean']) or
        not np.array_equal(std,prep['std']) or prep['groups']!=groups or
        prep['feature_order']!=policy['feature_order']):
        raise ValueError('TRAIN-only preprocessing mismatch')
    def describe(part):
        return dict(rows=len(part),dates=len({r['dependency_group'] for r in part}),
            first_utc=datetime.fromtimestamp(min(r['as_of'] for r in part),timezone.utc).isoformat(),
            last_utc=datetime.fromtimestamp(max(r['as_of'] for r in part),timezone.utc).isoformat(),
            label_end_utc=datetime.fromtimestamp(max(r['label_available_at'] for r in part),timezone.utc).isoformat())
    report=dict(scope='EXPOSED_DEV_PREPROCESSING_AUDIT',status='PASS',train=describe(train),
        diagnostic=describe(diagnostic),excluded=dict(Counter(r['exclusion_reason'] for r in rows if r['exclusion_reason'])),
        feature_order=policy['feature_order'],preprocessing=prep,source_hashes=hashes,
        code_hash=sha(Path(__file__)),trained=False,independent_oos=False,runtime_enabled=False,
        limitation='Proves frozen row/transform parity, not upstream feature correctness, model calibration or an unexposed feature-selection process. Population labels are gross returns, not trade net R.')
    if any(sha(ROOT/p)!=digest for p,digest in hashes.items()):
        raise ValueError('Source mutated during audit')
    out.mkdir(exist_ok=False);write_json(out/'report.json',report)
    print(json.dumps({k:report[k] for k in ('status','train','diagnostic','excluded')}))


if __name__=='__main__':main()
