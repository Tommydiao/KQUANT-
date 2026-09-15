"""Resolve only the frozen price-horizon branch; net-R plan contract unresolved."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_dataset_capsule import load_capsule
from kquant_crypto.hybrid_dev_fit import sha,write_json
from kquant_crypto.hybrid_reference_returns import six_hour_return
from kquant_crypto.hybrid_target_contract import interval_components


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();out=(ROOT/a.output).resolve()
    if not out.is_relative_to(ROOT/'outputs/hybrid_delivery') or out.exists():raise ValueError('New output required')
    source=ROOT/'outputs/hybrid_delivery/rx05_reference_selection_20260909_01'
    report=json.loads((source/'report.json').read_text());path=source/'reference_selection.jsonl'
    contract=ROOT/'config/rx05_entry_edge_attribution_01.json'
    if sha(path)!=report['selection_hash'] or sha(contract)!=report['policy_hash']:raise ValueError('Reference contract changed')
    data=load_capsule(ROOT/'outputs/hybrid_delivery/multifactor_dataset_capsule_20260909_01')
    if data.content_hash!=report['dataset_hash']:raise ValueError('Dataset changed')
    rows=[];intervals=[]
    for line in path.read_text().splitlines():
        selection=json.loads(line);signal=selection['signal'];ref=selection['reference']
        row=dict(economic_signal_id=selection['economic_signal_id'],symbol=signal['symbol'],mode=signal['mode'],selection_status=selection['status'])
        row['signal']=six_hour_return(signal['as_of'],data.bars[signal['symbol']]['5m'],data.cutoff)
        row['reference']=six_hour_return(ref['as_of'],data.bars[ref['symbol']]['5m'],data.cutoff) if ref else None
        valid=row['reference'] and row['signal']['status']==row['reference']['status']=='MATURE'
        row['paired_net_return_delta']=row['signal']['net_return']-row['reference']['net_return'] if valid else None
        if valid:intervals.append(dict(economic_key=[row['economic_signal_id']],information_start=ref['as_of'],information_end=signal['as_of']+21600))
        rows.append(row)
    valid=[r for r in rows if r['paired_net_return_delta'] is not None]
    out.mkdir(parents=True,exist_ok=False)
    with (out/'paired_returns.jsonl').open('x',encoding='utf-8') as f:
        for row in rows:f.write(json.dumps(row,allow_nan=False)+'\n')
    result=dict(scope='DEV_ONLY_EXPOSED',original_signals=len(rows),matched_resolved=len(valid),unmatched=sum(r['reference'] is None for r in rows),
        mean_signal_net_6h=sum(r['signal']['net_return'] for r in valid)/len(valid),
        mean_reference_net_6h=sum(r['reference']['net_return'] for r in valid)/len(valid),
        mean_paired_delta=sum(r['paired_net_return_delta'] for r in valid)/len(valid),
        improved=sum(r['paired_net_return_delta']>0 for r in valid),
        dependence_components=interval_components(intervals),
        execution_enabled=False,training_enabled=False,policy_net_r_evaluated=False,
        policy_net_r_blocker='Copying later original signal plan geometry to earlier reference time violates reference-time availability; no synthetic PIT plan claimed',
        independent_oos=False,performance='PERFORMANCE_UNPROVEN',
        source_selection_hash=sha(path),policy_hash=sha(contract),rows_hash=sha(out/'paired_returns.jsonl'),
        limitations=['Fixed6h price returns, not actual protected trading results','Matching conditioned on exposed original opportunities; observational, not causal','Paired information spans include reference-to-signal gap; not independent48samples'])
    write_json(out/'report.json',result);print(json.dumps({k:v for k,v in result.items() if k!='dependence_components'}));print('dependence_components='+str(len(result['dependence_components'])))


if __name__=='__main__':main()
