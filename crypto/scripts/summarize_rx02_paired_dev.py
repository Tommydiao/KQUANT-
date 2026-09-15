"""Fixed opportunity exit attribution; never portfolio performance or selection."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha,write_json


def paired_summary(rows):
    by_policy={name:{r['economic_signal_id']:r for r in rows if r['candidate']==name} for name in ('ORIGINAL','T1','T2')}
    if sum(len(v) for v in by_policy.values())!=len(rows):raise ValueError('Duplicate or unknown paired outcome')
    if any(set(v)!=set(by_policy['ORIGINAL']) for v in by_policy.values()):raise ValueError('Unmatched opportunities')
    result={}
    for name,index in by_policy.items():
        valid=[r for r in index.values() if r['net_r'] is not None]
        paired=[r for k,r in index.items() if r['net_r'] is not None and by_policy['ORIGINAL'][k]['net_r'] is not None]
        delta=[r['net_r']-by_policy['ORIGINAL'][r['economic_signal_id']]['net_r'] for r in paired]
        result[name]=dict(opportunities=len(index),resolved=len(valid),
            mean_net_r=sum(r['net_r'] for r in valid)/len(valid) if valid else None,
            paired_count=len(delta),mean_paired_delta=sum(delta)/len(delta) if delta else None,
            paired_improved=sum(d>1e-8 for d in delta),paired_worsened=sum(d< -1e-8 for d in delta),
            paired_unchanged=sum(abs(d)<=1e-8 for d in delta),
            exits=dict(Counter(r['reason'] for r in valid)))
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();out=(ROOT/a.output).resolve()
    if not out.is_relative_to(ROOT/'outputs/hybrid_delivery') or out.exists():raise ValueError('New independent output required')
    source=ROOT/'outputs/hybrid_delivery/rx02_fixed_opportunities_20260909_01'
    report=json.loads((source/'report.json').read_text());file=source/'counterfactual_outcomes.jsonl'
    if report['baseline_matches']!=27 or sha(file)!=report['rows_hash']:raise ValueError('Unverified outcome source')
    rows=[json.loads(l) for l in file.read_text().splitlines()]
    subsets={'ALL50':rows}
    for status in ('FILLED_VIRTUAL','NOT_FILLED'):subsets[status]=[r for r in rows if r['original_fill_status']==status]
    for symbol in sorted({r['symbol'] for r in rows}):subsets['SYMBOL:'+symbol]=[r for r in rows if r['symbol']==symbol]
    for mode in sorted({r['mode'] for r in rows}):subsets['MODE:'+mode]=[r for r in rows if r['mode']==mode]
    result=dict(scope='DEV_ONLY',subsets={key:paired_summary(value) for key,value in subsets.items()},
        source_hash=sha(file),code_hash=sha(Path(__file__)),execution_enabled=False,training_enabled=False,
        portfolio_performance=False,independent_oos=False,
        interpretation='Mean of fixed-BASE normalized hypothetical outcomes, not cash-weighted PF or causal benefit; original fill status is descriptive and post-policy selected',
        next='Preregister matched entry references before reading matched outcomes; no threshold selection authorized by this summary')
    out.mkdir(parents=True,exist_ok=False);write_json(out/'report.json',result)
    print(json.dumps({k:result['subsets'][k] for k in ('ALL50','FILLED_VIRTUAL','NOT_FILLED')}))


if __name__=='__main__':main()
