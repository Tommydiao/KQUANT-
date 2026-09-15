"""Instrument fixed path zero without changing decisions or stored MC outcomes."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import run_rx06_multistart_mc_dev as runner
from kquant_crypto.candidate_policy import load_policy
from kquant_crypto.hybrid_dev_fit import sha,write_json
from kquant_crypto.hybrid_conditioned_paths import conditioned_paths
from kquant_crypto.hybrid_mc_paths_v12 import DevPathSpec


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True)
    a=parser.parse_args();base=ROOT/'outputs/hybrid_delivery';out=(ROOT/a.output).resolve()
    if not out.is_relative_to(base) or out.exists():raise ValueError('New independent output required')
    run=base/'rx06_multistart_recovered_20260912_01'
    frozen=base/'rx06_multistarts_20260909_01'
    report=json.loads((run/'report.json').read_text());prereg=json.loads((run/'preregistration.json').read_text())
    for name,digest in {**prereg['code_hashes'],**prereg['frozen']['code_hashes']}.items():
        if sha(ROOT/name)!=digest:raise ValueError('Frozen source mismatch: '+name)
    policy=load_policy(candidate='A');rules_path=ROOT/'outputs/dual_regime_v1/exchange_rules.json'
    if policy['policy_hash']!=prereg['frozen']['original_policy_hash'] or sha(rules_path)!=prereg['frozen']['rules_hash']:
        raise ValueError('Frozen policy or rules mismatch')
    rules=json.loads(rules_path.read_text())['rules']
    if sha(frozen/'start_index.json')!=prereg['index_hash']:raise ValueError('Start selection changed')
    index={r['as_of']:r for r in json.loads((frozen/'start_index.json').read_text())}
    source_hashes={str(run.relative_to(ROOT)/'report.json'):sha(run/'report.json')}
    out.mkdir(exist_ok=False)
    write_json(out/'preregistration.json',dict(scope='EXPOSED_DEV_FIXED_PATH_DIAGNOSTIC',
        selection='Path0 at EVERY previously eligible frozen start; no search or new draws',
        runtime_enabled=False,code_hash=sha(Path(__file__)),source_report_hash=sha(run/'report.json'),
        risk_gate_changed=False,new_orders=False))
    results=[]
    original_class=runner.ExistingExposurePortfolio
    for item in report['starts']:
        if item['status']!='COMPLETED':continue
        meta=index[item['as_of']];path=frozen/meta['snapshot_file']
        if sha(path)!=meta['snapshot_hash']:raise ValueError('Snapshot changed')
        snap=json.loads(path.read_text());spec=DevPathSpec(**item['spec'])
        generated=next(conditioned_paths(snap['history'],snap['anchors'],spec,snap['regime']))
        source=run/f"paths_{item['as_of']}.jsonl"
        if sha(source)!=item['path_hash']:raise ValueError('Path evidence changed')
        source_hashes[str(source.relative_to(ROOT))]=sha(source)
        with source.open() as f:saved=json.loads(f.readline())
        if saved['path_id']!=0 or saved['sampling_hash']!=generated['sampling_hash']:
            raise ValueError('Fixed path mismatch')
        traces=[]
        def record(port,time,phase):
            holdings=[*port.positions.values(),*port.pending.values()]
            risk=sum(v.get('estimated_risk_amount',v['risk_amount']) for v in holdings)
            nav=port.value();limit=nav*policy['max_open_risk']
            traces.append(dict(policy=port.exit_candidate,time=time,phase=phase,
                nav=nav,booked_risk=risk,budget=limit,excess_cash=risk-limit,
                exceeded=risk>limit+1e-8,positions=len(port.positions),pending=len(port.pending)))
        class TracedPortfolio(original_class):
            def restore(self,state):
                super().restore(state);record(self,snap['as_of'],'INITIAL')
            def on_path_batch(self,bars,hourly,now):
                super().on_path_batch(bars,hourly,now);record(self,now,'POST_BATCH')
        try:
            runner.ExistingExposurePortfolio=TracedPortfolio
            outcome=runner.simulate(snap,generated,policy,rules,prereg['frozen']['config']['policies'])
        finally:
            runner.ExistingExposurePortfolio=original_class
        if outcome!=saved['results']:raise ValueError('Instrumentation changed frozen result')
        file=out/f"trace_{snap['as_of']}_path0.jsonl"
        with file.open('x',encoding='utf-8') as f:
            for row in traces:f.write(json.dumps(row,allow_nan=False)+'\n')
        per_policy={}
        for candidate in outcome:
            rows=[r for r in traces if r['policy']==candidate]
            if len(rows)!=spec.horizon_bars+1:raise ValueError('Incomplete trace')
            after=[r for r in rows[1:] if r['exceeded']]
            if bool(after)!=outcome[candidate]['budget_exceeded']:raise ValueError('Risk flag parity failed')
            per_policy[candidate]=dict(initial=rows[0],first_post_batch_flag=after[0] if after else None,
                flagged_batches=len(after),max_excess_cash=max(r['excess_cash'] for r in rows),
                interpretation='Inherited initial threshold exceedance' if rows[0]['exceeded'] else
                    ('Post-start threshold crossing' if after else 'No threshold crossing on this fixed path'))
        results.append(dict(as_of=snap['as_of'],path_id=0,outcome_parity=True,
            trace_hash=sha(file),policies=per_policy))
    if any(sha(ROOT/name)!=digest for name,digest in source_hashes.items()):raise ValueError('Original outputs changed')
    write_json(out/'report.json',dict(scope='DEV_ONLY_FIXED_PATH_DIAGNOSTIC',starts=results,
        source_hashes=source_hashes,execution_enabled=False,risk_gate_pass=False,
        limitation='Only path0 trace at each eligible start; does not estimate event probabilities, new-position safety or real market losses. Booked entry risk is not current remaining stop risk.'))
    print(json.dumps(dict(starts=len(results),all_outcomes_match=True)))


if __name__=='__main__':main()
