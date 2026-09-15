"""Capital/time concentration from immutable full portfolio replay outputs."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha,write_json
from kquant_crypto.hybrid_exposure_audit import exposure_audit


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    out=(ROOT/a.output).resolve();base=ROOT/'outputs/hybrid_delivery'
    if not out.is_relative_to(base) or out.exists():raise ValueError('New isolated output required')
    capsule=base/'multifactor_dataset_capsule_20260909_01/capsule.json'
    contract=json.loads(capsule.read_text());start=contract['original_manifest']['window']['start'];end=contract['cutoff']
    results={};hashes={}
    for candidate in ('ORIGINAL','T1','T2'):
        folder=base/'multifactor_portfolio_20260907_02'/(candidate+'_1')
        inputs={}
        for kind in ('trades','equity'):
            file=folder/(kind+'.jsonl');hashes[str(file.relative_to(ROOT))]=sha(file)
            inputs[kind]=[json.loads(s) for s in file.read_text().splitlines()]
        results[candidate]=exposure_audit(inputs['trades'],inputs['equity'],start,end,['BTCUSDT','ETHUSDT','SOLUSDT'])
    out.mkdir(exist_ok=False)
    result=dict(scope='EXPOSED_DEV_POSTHOC_ATTRIBUTION',results=results,source_hashes=hashes,
        source_unchanged=all(sha(ROOT/n)==v for n,v in hashes.items()),capsule_hash=sha(capsule),
        code_hash=sha(Path(__file__)),helper_hash=sha(ROOT/'kquant_crypto/hybrid_exposure_audit.py'),
        runtime_enabled=False,performance='RESEARCH_NO_GO')
    write_json(out/'report.json',result)
    print(json.dumps({k:{n:v[n] for n in ('trades','calendar_days','any_position_time_fraction',
        'time_weighted_costed_position_value_fraction','best_net_asset','net_pnl_excluding_best_net_asset')} for k,v in results.items()}))


if __name__=='__main__':main()
