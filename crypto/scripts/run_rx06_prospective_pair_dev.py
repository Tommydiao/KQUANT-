"""Bounded isolated paired pending-risk replay; never produces trade permissions."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.candidate_policy import load_policy
from kquant_crypto.hybrid_dev_fit import sha,write_json
from kquant_crypto.hybrid_conditioned_paths import conditioned_paths
from kquant_crypto.hybrid_mc_paths_v12 import DevPathSpec,audit_history
from kquant_crypto.hybrid_prospective_risk import simulate_pair
from kquant_crypto.hybrid_mc_recovery import read_pair_prefix


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True)
    p.add_argument('--phase',choices=('engineering','full'),required=True)
    p.add_argument('--resume-from',help='Read-only previous run; validated rows copied into new output')
    a=p.parse_args()
    base=ROOT/'outputs/hybrid_delivery';out=(ROOT/a.output).resolve()
    if not out.is_relative_to(base) or out.exists():raise ValueError('New independent output required')
    config_path=ROOT/'config/rx06_prospective_pair_dev_v1.json';config=json.loads(config_path.read_text())
    frozen=base/'rx06_prospective_states_20260912_01'
    summary=json.loads((frozen/'report.json').read_text());prereg=json.loads((frozen/'preregistration.json').read_text())
    index=frozen/'state_index.json'
    if sha(index)!=summary['index_hash'] or not all(summary['parity'].values()):
        raise ValueError('Frozen state population/parity mismatch')
    records=json.loads(index.read_text());policy=load_policy(candidate='A')
    if policy!=prereg['policy']:raise ValueError('Frozen policy mismatch')
    for name,digest in prereg['implementation_hashes'].items():
        if sha(ROOT/name)!=digest:raise ValueError('Frozen implementation changed')
    rules_path=ROOT/'outputs/dual_regime_v1/exchange_rules.json'
    original=json.loads((base/'multifactor_portfolio_20260907_02/preregistration.json').read_text())
    if sha(rules_path)!=original['rules_hash']:raise ValueError('Frozen exchange rules mismatch')
    rules=json.loads(rules_path.read_text())['rules']
    count=config['engineering_paths_per_record'] if a.phase=='engineering' else config['paths_per_record']
    inputs={str(path.relative_to(ROOT)):sha(path) for path in (index,config_path,rules_path,
        ROOT/'kquant_crypto/hybrid_prospective_risk.py',ROOT/'kquant_crypto/hybrid_conditioned_paths.py',
        ROOT/'kquant_crypto/hybrid_mc_recovery.py')}
    contract=dict(config=config,phase=a.phase,paths_per_record=count,
        source_hashes=inputs,code_hash=sha(Path(__file__)),execution_enabled=False)
    prior=(ROOT/a.resume_from).resolve() if a.resume_from else None
    previous_hashes={}
    if prior:
        if not prior.is_relative_to(base) or prior==out:raise ValueError('Independent prior run required')
        if json.loads((prior/'preregistration.json').read_text())!=contract:
            raise ValueError('Prior phase, source or code version mismatch')
        previous_hashes={str(path.relative_to(ROOT)):sha(path) for path in prior.glob('pair_*.jsonl')}
    out.mkdir(exist_ok=False)
    write_json(out/'preregistration.json',contract)
    if prior:write_json(out/'recovery_manifest.json',dict(prior=str(prior),prior_path_hashes=previous_hashes))
    outcomes=[]
    for i,record in enumerate(records):
        identity={k:record[k] for k in ('economic_signal_id','policy','symbol','mode','signal_time')}
        if not record['admitted']:
            if prior and (prior/f'pair_{i:03d}.jsonl').exists():raise ValueError('Path for rejected record')
            outcomes.append(dict(**identity,status='ORIGINAL_REJECTION',reason=record['reason']));continue
        context_path=(frozen/record['context']['file']).resolve()
        snapshot_path=(frozen/record['snapshot_file']).resolve()
        for path,digest in ((context_path,record['context']['hash']),(snapshot_path,record['snapshot_hash'])):
            if not path.is_relative_to(frozen) or sha(path)!=digest:raise ValueError('State/context mismatch')
        context=json.loads(context_path.read_text());state=json.loads(snapshot_path.read_text())['state']
        as_of=record['signal_time'];history=context['history']
        if context['as_of']!=as_of or not context['history_contiguous']:raise ValueError('Time/history contract mismatch')
        spec=DevPathSpec(history[0]['start'],as_of,as_of,config['block_bars'],config['horizon_bars'],
            count,config['seed'],config['history_bars'],count*config['horizon_bars']*3,
            context['source_dataset_hash'],'EXPOSED_DEV_AUTHORIZED')
        audit=audit_history(history,spec)
        blocks=sum(history[j]['regime_before']==context['regime'] for j in audit['eligible_block_starts'])
        if len(history)!=config['history_bars'] or blocks<config['minimum_conditioned_blocks']:
            if prior and (prior/f'pair_{i:03d}.jsonl').exists():raise ValueError('Path for unavailable record')
            outcomes.append(dict(**identity,status='UNAVAILABLE',reason='INSUFFICIENT_HISTORY_OR_CONDITIONED_BLOCKS',blocks=blocks));continue
        file=out/f'pair_{i:03d}.jsonl';total=0.;filled=Counter();open_horizon=Counter()
        saved,raw=read_pair_prefix(prior/file.name,count) if prior else ([],b'')
        lines=raw.splitlines(keepends=True)
        with file.open('xb') as f:
            for generated in conditioned_paths(history,context['anchors'],spec,context['regime']):
                n=generated['path_id']
                if n<len(saved):
                    row=saved[n]
                    if row['sampling_hash']!=generated['sampling_hash']:raise ValueError('Resumed path sequence mismatch')
                    encoded=lines[n]
                else:
                    result=simulate_pair(state,context,generated,policy,rules,record['policy'],record['symbol'])
                    row=dict(path_id=n,sampling_hash=generated['sampling_hash'],**result)
                    encoded=(json.dumps(row,allow_nan=False)+'\n').encode()
                f.write(encoded);total+=row['paired_net_change']
                for name,v in row['results'].items():
                    filled[name]+=v['target_plan_fills'];open_horizon[name]+=v['open_at_horizon']>0
                if (n+1)%100==0:
                    f.flush()
                    write_json(out/'progress.json',dict(record=i,paths_done=n+1,total_paths=count,reused=len(saved)))
                    print(json.dumps(dict(record=i,paths_done=n+1,reused=len(saved))),flush=True)
            f.flush()
        outcomes.append(dict(**identity,status='COMPLETED',paths=count,path_file=file.name,path_hash=sha(file),
            mean_paired_net_change=total/count,target_plan_fills=dict(filled),horizon_open_paths=dict(open_horizon)))
        write_json(out/'progress.json',dict(records_done=len(outcomes),total_records=len(records)))
        print(json.dumps(dict(record=i,paths=count,status='COMPLETED')),flush=True)
    if any(sha(ROOT/name)!=digest for name,digest in {**inputs,**previous_hashes}.items()):raise ValueError('Inputs or prior paths changed during run')
    write_json(out/'report.json',dict(scope=config['scope'],phase=a.phase,records=outcomes,
        status_counts=dict(Counter(r['status'] for r in outcomes)),execution_enabled=False,
        calibrated_risk=False,performance='PERFORMANCE_UNPROVEN',
        limitation='Conditional paired terminal valuation, no realistic execution latency, no posterior uncertainty. Engineering paths test plumbing only. Never pooled as independent trades or used for strategy selection.'))
    print(json.dumps(dict(status_counts=dict(Counter(r['status'] for r in outcomes)))))


if __name__=='__main__':main()
