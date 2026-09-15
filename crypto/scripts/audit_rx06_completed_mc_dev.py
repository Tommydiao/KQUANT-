"""Read-only full path/hash audit. Incomplete run is rejected, never promoted."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha,write_json
from kquant_crypto.hybrid_mc_recovery import read_prefix
from kquant_crypto.hybrid_mc_result_audit import summarize_path_events,verify_numeric_summary
from kquant_crypto.hybrid_mc_dependencies import audit_dependencies
from kquant_crypto.hybrid_mc_paths_v12 import DevPathSpec,audit_history
from kquant_crypto.candidate_policy import load_policy


def main():
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    run,out=[(ROOT/v).resolve() for v in (a.run,a.output)];base=ROOT/'outputs/hybrid_delivery'
    if any(not v.is_relative_to(base) for v in (run,out)) or out.exists():raise ValueError('New independent report required')
    report=json.loads((run/'report.json').read_text())
    if report['requested_paths_per_start']!=5000 or report['runtime_enabled'] is not False:
        raise ValueError('Unexpected final run contract')
    frozen=base/'rx06_multistarts_20260909_01'
    index=json.loads((frozen/'start_index.json').read_text())
    prior=json.loads((run/'preregistration.json').read_text())
    policy=load_policy(candidate='A')
    if policy['policy_hash']!=prior['frozen']['original_policy_hash']:
        raise ValueError('Frozen risk policy mismatch')
    if sha(frozen/'start_index.json')!=prior['index_hash']:raise ValueError('Start selection changed')
    starts=report['starts']
    if [r['as_of'] for r in starts]!=[r['as_of'] for r in index]:raise ValueError('Missing or reordered starts')
    dependencies=json.loads((base/'rx06_dependencies_20260910_01/report.json').read_text())
    if dependencies['index_hash']!=prior['index_hash']:raise ValueError('Dependency population mismatch')
    results=[];eligible=[]
    for item,state in zip(index,starts):
        snapshot=(frozen/item['snapshot_file']).resolve()
        if not snapshot.is_relative_to(frozen) or sha(snapshot)!=item['snapshot_hash']:
            raise ValueError('Frozen snapshot changed')
        snap=json.loads(snapshot.read_text());config=prior['frozen']['config']
        spec=DevPathSpec(snap['history'][0]['start'],snap['as_of'],snap['as_of'],
            config['block_bars'],config['horizon_bars'],5000,config['seed'],config['history_bars'],
            5000*config['horizon_bars']*3,snap['source_dataset_hash'],'EXPOSED_DEV_AUTHORIZED')
        history=audit_history(snap['history'],spec)
        block_count=sum(snap['history'][i]['regime_before']==snap['regime'] for i in history['eligible_block_starts'])
        if state['status']=='UNAVAILABLE':
            if (state['reason']!='INSUFFICIENT_CONDITIONED_BLOCKS' or
                    state['eligible_blocks']!=block_count or block_count>=config['minimum_conditioned_blocks']):
                raise ValueError('Unexplained unavailable start')
            results.append(dict(as_of=state['as_of'],status='UNAVAILABLE',reason=state['reason']));continue
        if state['status']!='COMPLETED' or state['paths']!=5000 or block_count<config['minimum_conditioned_blocks']:
            raise ValueError('Partial or ineligible start is not completed')
        file=run/f"paths_{item['as_of']}.jsonl"
        if sha(file)!=state['path_hash']:raise ValueError('Path hash mismatch')
        rows,_=read_prefix(file,('ORIGINAL','T1','T2'),5000)
        summaries={c:summarize_path_events([r['results'][c] for r in rows],5000) for c in ('ORIGINAL','T1','T2')}
        for c in summaries:
            summaries[c]['verified_numeric_summary']=verify_numeric_summary(
                [r['results'][c] for r in rows],state['summary'][c])
            holdings=[*snap['states'][c]['positions'].values(),*snap['states'][c]['pending'].values()]
            initial_risk=sum(v.get('estimated_risk_amount',v['risk_amount']) for v in holdings)
            nav=snap['initial_values'][c]
            summaries[c]['budget_interpretation']=dict(initial_booked_risk_cash=initial_risk,
                initial_nav=nav,initial_ratio=initial_risk/nav,
                definition='Booked estimated entry risk / current costed NAV, checked after each simulated batch; not realized loss, stop-to-current remaining risk or an order admission event.',
                initial_budget_exceeded=initial_risk>nav*policy['max_open_risk']+1e-8,
                open_risk_budget_fraction=policy['max_open_risk'],
                first_breach_time_recorded=False,
                limitation='Initial breach is disclosed separately; saved per-path boolean cannot distinguish inherited breach from first post-start breach. No risk-success gate assigned.')
        results.append(dict(as_of=item['as_of'],status='AUDITED',path_hash=state['path_hash'],policies=summaries))
        eligible.append(item['as_of'])
    grouped=audit_dependencies([r for r in dependencies['frozen_rows'] if r['as_of'] in eligible])
    result=dict(scope='DEV_ONLY_CONDITIONAL_MC_AUDIT',starts=results,
        completed_starts=len(eligible),joint_paths=len(eligible)*5000,
        eligible_dependency_audit=grouped,source_report_hash=sha(run/'report.json'),
        independent_market_sample_count=None,performance='PERFORMANCE_UNPROVEN',
        ten_r_gate='UNRESOLVED_NOT_EVALUATED',runtime_enabled=False,code_hash=sha(Path(__file__)),
        limitation='No cross-start pooled success probability or policy selection. Path counts are not real trades. NAV drawdown not converted into an unapproved R denominator.')
    out.mkdir(exist_ok=False);write_json(out/'report.json',result)
    print(json.dumps(dict(completed_starts=len(eligible),joint_paths=len(eligible)*5000,dependency_components=len(grouped['components']))))


if __name__=='__main__':main()
