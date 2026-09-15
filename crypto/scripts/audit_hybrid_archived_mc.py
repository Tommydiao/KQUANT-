"""Recompute only frozen engineering comparisons; never resample or select size."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_delivery import atomic_json, load, sha
from kquant_crypto.hybrid_mc_comparison_v12 import summarize_common_paths


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',required=True)
    args=p.parse_args()
    out=(ROOT/args.output).resolve()
    if not out.is_relative_to(ROOT/'outputs/hybrid_delivery'):
        raise ValueError('Independent evidence required')
    out.mkdir(parents=True,exist_ok=False)
    source=ROOT/'outputs/hybrid_delivery/t21_alternatives_5000_20260906_01'
    report=load(source/'report.json')
    archive=source/'paths.jsonl.gz'
    if sha(archive)!=report['compressed_sha256'] or report['completed']!=5000:
        raise ValueError('Frozen archive mismatch')
    records=[]
    chain=hashlib.sha256()
    count=0
    with gzip.open(archive,'rt',encoding='utf-8') as stream:
        for line in stream:
            chain.update(line.rstrip('\n').encode())
            row=json.loads(line)
            if row['path_id']!=count or count>=5000:
                raise ValueError('Path sequence mismatch')
            for a in (0,.25,.5,1):
                records.append({'path_id':count,'alternative':a,'events':{
                    'daily_loss':row['costs'][f'{a}:1']['risk']['daily_loss_line_breached']}})
            count+=1
    if count!=5000 or chain.hexdigest()!=report['record_hash']:
        raise ValueError('Incomplete or changed records')
    result=summarize_common_paths(records,path_ids=list(range(count)),alternatives=(0,.25,.5,1),
                                 event_names=['daily_loss'],family_alpha=.05,comparison_budget=4)
    matches=result==load(source/'comparison.json')
    atomic_json(out/'evidence.json',{'exact_comparison_match':matches,'paths':count,
                'archive_sha256':sha(archive),'record_hash':chain.hexdigest(),
                'recomputed':result,'resampled':False,'G4_passed':False,
                'source_run':str(source.relative_to(ROOT)),'python':sys.executable})
    return 0 if matches else 1


if __name__=='__main__':
    raise SystemExit(main())
