"""Audit frozen starts without reading outcomes or restricted historical rows."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha,write_json
from kquant_crypto.hybrid_mc_dependencies import audit_dependencies


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    args=parser.parse_args();base=ROOT/'outputs/hybrid_delivery'
    source=base/'rx06_multistarts_20260909_01';out=(ROOT/args.output).resolve()
    if not out.is_relative_to(base) or out.exists():raise ValueError('New isolated output required')
    report=json.loads((source/'report.json').read_text())
    contract=json.loads((source/'preregistration.json').read_text())
    if sha(source/'start_index.json')!=report['index_hash']:raise ValueError('Start index changed')
    index=json.loads((source/'start_index.json').read_text());rows=[]
    for item in index:
        path=(source/item['snapshot_file']).resolve()
        if not path.is_relative_to(source) or sha(path)!=item['snapshot_hash']:raise ValueError('Snapshot changed')
        snap=json.loads(path.read_text());keys=set();policies={}
        for policy,state in snap['states'].items():
            identities=[]
            for kind in ('positions','pending'):
                for symbol,position in state[kind].items():
                    key=(symbol,position['mode'],position['signal_time'])
                    if key[2]>snap['as_of']:raise ValueError('Future exposure')
                    keys.add(key);identities.append(dict(kind=kind,economic_key=list(key),trade_id=position['trade_id']))
            policies[policy]=identities
        rows.append(dict(as_of=snap['as_of'],history_start=snap['history'][0]['start'],
            scenario_end=snap['as_of']+contract['config']['horizon_bars']*300,
            economic_keys=[list(k) for k in sorted(keys)],policies=policies,regime=snap['regime']))
    result=audit_dependencies(rows)
    result.update(scope='DEV_ONLY_DEPENDENCY_AUDIT',frozen_rows=rows,index_hash=report['index_hash'],
        code_hash=sha(Path(__file__)),helper_hash=sha(ROOT/'kquant_crypto/hybrid_mc_dependencies.py'),
        runtime_enabled=False,performance='PERFORMANCE_UNPROVEN',new_outcomes_read=False)
    out.mkdir(exist_ok=False);write_json(out/'report.json',result)
    print(json.dumps(dict(starts=result['starts'],components=result['components'],edges=len(result['edges']))))


if __name__=='__main__':main()
