"""One frozen research snapshot, synchronized conditional paths, no orders."""
import argparse
from collections import deque
from dataclasses import asdict
import datetime
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.candidate_policy import load_policy
from kquant_crypto.hybrid_dataset import load_development
from kquant_crypto.hybrid_dataset_capsule import load_capsule
from kquant_crypto.hybrid_dev_fit import sha,write_json
from kquant_crypto.hybrid_research_portfolio import ResearchPortfolio
from kquant_crypto.hybrid_conditioned_paths import conditioned_paths
from kquant_crypto.hybrid_mc_paths_v12 import DevPathSpec,SYMBOLS
from kquant_crypto.strategy_dual_mode_v1 import Bar


def parse_deadline(value):
    if value is None:
        return None
    deadline=datetime.datetime.fromisoformat(value.replace('Z','+00:00'))
    if deadline.tzinfo is None:
        raise ValueError('Deadline requires explicit timezone')
    return deadline.astimezone(datetime.timezone.utc)


def deadline_reached(deadline):
    return deadline is not None and datetime.datetime.now(datetime.timezone.utc)>=deadline


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True)
    p.add_argument('--paths',type=int,default=5000)
    p.add_argument('--capsule',help='Authorized DEV-only portable data directory')
    p.add_argument('--deadline-utc',help='Optional operational cutoff, timezone required')
    a=p.parse_args();out=(ROOT/a.output).resolve()
    deadline=parse_deadline(a.deadline_utc)
    capsule=(ROOT/a.capsule).resolve() if a.capsule else None
    if not out.is_relative_to(ROOT/'outputs/hybrid_delivery') or a.paths not in (2,5000):
        raise ValueError('Only smoke2 or registered5000 research paths allowed')
    out.mkdir(parents=True,exist_ok=False)
    candidates=('ORIGINAL','FIXED_2_5R','FIXED_3R','T1','T2')
    config={'scope':'DEV_ONLY','paths':a.paths,'seed':20260907,'block_bars':12,'horizon_bars':576,
        'conditioning':'BTC closed regime before historical block; current snapshot BTC regime',
        'snapshot_selection':'first original A live virtual position after authorized development start',
        'new_entries':False,'model_uncertainty_added':False,'execution_enabled':False,
        'operational_deadline':deadline.isoformat() if deadline else None,
        'capsule_manifest_hash':sha(capsule/'capsule.json') if capsule else None,
        'end_policy':'costed mark, open positions not closed or counted as realized',
        'candidates':candidates,'source_hashes':{name:sha(ROOT/name) for name in (
            'scripts/run_multifactor_mc_dev.py','kquant_crypto/hybrid_conditioned_paths.py',
            'kquant_crypto/hybrid_research_portfolio.py','kquant_crypto/candidate_simulation.py',
            'kquant_crypto/hybrid_exit_research.py','kquant_crypto/hybrid_dataset_capsule.py')}}
    write_json(out/'preregistration.json',config)
    data=load_capsule(capsule) if capsule else load_development(ROOT/'outputs/dual_regime_v1/frozen/data_manifest.json')
    policy=load_policy(candidate='A')
    rules=json.loads((ROOT/'outputs/dual_regime_v1/exchange_rules.json').read_text())['rules']
    portfolios={c:ResearchPortfolio(policy,rules,exit_candidate=c) for c in candidates}
    timeline={}; hours={}
    for s,frames in data.bars.items():
        for b in frames['5m']:timeline.setdefault(b.start,{})[s]=b
        for b in frames['1h']:hours.setdefault(b.start+3600,{})[s]=b
    history=deque(maxlen=2017)
    for start,bars in sorted(timeline.items()):
        before=portfolios['ORIGINAL'].kernels['BTCUSDT'].mode
        history.append({'start':start,'regime_before':before,'bars':{
            s:{**asdict(b),'available_at':start+300,'source_bar_id':f'{s}:{start}'} for s,b in bars.items()}})
        for portfolio in portfolios.values():
            portfolio.on_closed_batch(bars,hours.get(start+300,{}),start+300,
                allow_entries=start+300>=data.manifest['window']['start'])
            portfolio.drain()
        if portfolios['ORIGINAL'].positions:
            as_of=start+300;break
    else:raise ValueError('No original A snapshot with existing position')
    states={c:p.snapshot() for c,p in portfolios.items()}
    history=list(history)
    spec=DevPathSpec(history[0]['start'],as_of,as_of,12,576,a.paths,20260907,2017,
                     a.paths*576*3,data.content_hash,'EXPOSED_DEV_AUTHORIZED')
    anchors=portfolios['ORIGINAL'].marks
    regime=portfolios['ORIGINAL'].kernels['BTCUSDT'].mode
    write_json(out/'snapshot.json',{'as_of':as_of,'states':states,'spec':asdict(spec),
                                  'history':history,'anchors':anchors,'regime':regime})
    totals={c:[] for c in candidates}
    completed=0
    with (out/'path_results.jsonl').open('x',encoding='utf-8') as handle:
        for path in conditioned_paths(history,anchors,spec,regime):
            if deadline_reached(deadline):
                break
            ports={c:ResearchPortfolio(policy,rules,exit_candidate=c) for c in candidates}
            for c,port in ports.items():port.restore(json.loads(json.dumps(states[c])))
            initial={c:port.value() for c,port in ports.items()}; peaks=dict(initial)
            dd={c:0. for c in candidates}; stopped={c:False for c in candidates}
            budget={c:False for c in candidates}
            prefix={s:[Bar(**{k:b['bars'][s][k] for k in ('start','open','high','low','close','volume')})
                       for b in history if b['start']>=as_of//3600*3600] for s in SYMBOLS}
            for batch in path['batches']:
                now=batch['BTCUSDT'].start+300; hour={}
                for s,bar in batch.items():
                    prefix[s].append(bar)
                    if now%3600==0:
                        seq=prefix[s]
                        if len(seq)!=12:raise ValueError('Incomplete generated hour')
                        hour[s]=Bar(seq[0].start,seq[0].open,max(b.high for b in seq),min(b.low for b in seq),seq[-1].close,0)
                        prefix[s]=[]
                for c,port in ports.items():
                    port.on_closed_batch(batch,hour,now,allow_entries=False)
                    drained=port.drain()
                    stopped[c]|=any(t['exit_reason'] in ('stop','gap_stop') for t in drained['trades'])
                    value=port.value();peaks[c]=max(peaks[c],value);dd[c]=max(dd[c],(peaks[c]-value)/peaks[c])
                    budget[c]|=sum(t.get('estimated_risk_amount',t['risk_amount']) for t in port.positions.values())>value*policy['max_open_risk']+1e-8
            row={'path_id':path['path_id'],'sampling_hash':path['sampling_hash'],'results':{}}
            for c,port in ports.items():
                result={'net_change':port.value()-initial[c],'max_drawdown_fraction':dd[c],
                        'stop_hit':stopped[c],'budget_exceeded':budget[c],'open_at_horizon':len(port.positions)}
                totals[c].append(result);row['results'][c]=result
            handle.write(json.dumps(row,allow_nan=False)+'\n');completed+=1
            if completed%100==0:
                handle.flush();print(json.dumps({'completed':completed,'requested':a.paths}),flush=True)
    import numpy as np
    summary={c:{'net_change_quantiles':np.quantile([r['net_change'] for r in rows],[.1,.5,.9]).tolist(),
                'stop_fraction':sum(r['stop_hit'] for r in rows)/len(rows),
                'budget_exceeded_fraction':sum(r['budget_exceeded'] for r in rows)/len(rows),
                'open_at_horizon_fraction':sum(r['open_at_horizon']>0 for r in rows)/len(rows)}
             for c,rows in totals.items() if rows}
    result={'completed':completed,'requested':a.paths,'scope':'DEV_ONLY','market_samples':1,
            'status':'COMPLETED' if completed==a.paths else 'DEADLINE_PARTIAL',
            'summary':summary,'path_results_hash':sha(out/'path_results.jsonl'),
            'calibrated_risk':False,'performance':'PERFORMANCE_UNPROVEN'}
    write_json(out/'report.json',result);print(json.dumps(result))


if __name__=='__main__':main()
