"""Create a fixed fold manifest without reading restricted history or fitting."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha,write_json
from kquant_crypto.hybrid_opportunity_folds import build_folds


def main():
    p=argparse.ArgumentParser();p.add_argument('--population',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();source=(ROOT/a.population).resolve();out=(ROOT/a.output).resolve()
    if any(not path.is_relative_to(ROOT/'outputs/hybrid_delivery') for path in (source,out)):
        raise ValueError('Independent DEV paths required')
    report=json.loads((source/'report.json').read_text())
    if sha(source/'population.jsonl')!=report['population_hash']:
        raise ValueError('Population changed')
    out.mkdir(exist_ok=False)
    write_json(out/'preregistration.json',{'scope':'DEV_ONLY','selection':False,'fit':False,
        'calendar':'outer40-60,60-80,80-100% authorized DEV; inner70% of prior calendar',
        'target':'fixed24h descriptive outcome only','embargo_seconds':86400,
        'population_hash':report['population_hash'],'code_hash':sha(Path(__file__)),
        'fold_code_hash':sha(ROOT/'kquant_crypto/hybrid_opportunity_folds.py')})
    manifest=json.loads((ROOT/'outputs/dual_regime_v1/frozen/data_manifest.json').read_text())
    rows=[json.loads(s) for s in (source/'population.jsonl').read_text().splitlines()]
    result=build_folds(rows,manifest['window']['start'],report['authorized_cutoff'])
    result['population_hash']=report['population_hash']
    write_json(out/'fold_manifest.json',result)
    print(json.dumps({'counts':[r['counts'] for r in result['folds']],
        'manifest_hash':sha(out/'fold_manifest.json'),'independent_oos':False,'fit_executed':False}))


if __name__=='__main__':main()
