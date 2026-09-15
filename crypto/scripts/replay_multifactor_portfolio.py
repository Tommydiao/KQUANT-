"""Authorized full-portfolio exit research, independent outputs and no orders."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.candidate_policy import load_policy
from kquant_crypto.candidate_simulation import CandidatePortfolio
from kquant_crypto.hybrid_research_portfolio import ResearchPortfolio
from kquant_crypto.hybrid_dataset import load_development
from kquant_crypto.hybrid_dataset_capsule import load_capsule
from kquant_crypto.hybrid_dev_fit import sha,write_json


def run(portfolio,timeline,hours,start,end,out):
    trades=[]; counts=Counter(); equity=[]
    with (out/'events.jsonl').open('x',encoding='utf-8') as events:
        for timestamp,bars in sorted(timeline.items()):
            close=timestamp+300
            portfolio.on_closed_batch(bars,hours.get(close,{}),close,
                                      allow_entries=start<=close<=end-21600)
            drained=portfolio.drain()
            for event in drained['events']:
                counts[event['kind']+':'+str(event.get('reason',''))]+=1
                if event['kind']!='CLOSED_BAR_DECISION':
                    events.write(json.dumps(event,sort_keys=True,allow_nan=False)+'\n')
            trades.extend(drained['trades']); equity.extend(drained['equity'])
        portfolio.finish(end)
        drained=portfolio.drain()
        trades.extend(drained['trades'])
        if equity and equity[-1]['time']==end:
            equity.pop()
        equity.extend(drained['equity'])
        for event in drained['events']:
            events.write(json.dumps(event,sort_keys=True,allow_nan=False)+'\n')
    for name,rows in [('trades',trades),('equity',equity)]:
        with (out/(name+'.jsonl')).open('x',encoding='utf-8') as handle:
            for row in rows:
                handle.write(json.dumps(row,sort_keys=True,allow_nan=False)+'\n')
    gains=sum(max(0,t['net_pnl']) for t in trades)
    losses=sum(max(0,-t['net_pnl']) for t in trades)
    peak=portfolio.policy['initial_cash']; drawdown=0
    for row in equity:
        peak=max(peak,row['equity']); drawdown=max(drawdown,(peak-row['equity'])/peak)
    result={'trades':len(trades),'mean_net_r':sum(t['net_r'] for t in trades)/len(trades) if trades else None,
            'net_pnl':sum(t['net_pnl'] for t in trades),'profit_factor':gains/losses if losses else None,
            'max_drawdown_fraction':drawdown,'final_equity':portfolio.value(),
            'terminal_liquidations':sum(t['exit_reason']=='terminal_liquidation' for t in trades),
            'event_counts':dict(counts),'trade_hash':sha(out/'trades.jsonl'),'equity_hash':sha(out/'equity.jsonl')}
    write_json(out/'report.json',result)
    return trades,equity,result


def main():
    p=argparse.ArgumentParser(); p.add_argument('--output',required=True)
    p.add_argument('--capsule', help='Authorized DEV-only portable data directory')
    p.add_argument('--verify-reference', help='Existing research run for exact replay comparison')
    args=p.parse_args()
    out=(ROOT/args.output).resolve()
    if not out.is_relative_to(ROOT/'outputs/hybrid_delivery'):
        raise ValueError('Independent output required')
    out.mkdir(parents=True,exist_ok=False)
    rules_path=ROOT/'outputs/dual_regime_v1/exchange_rules.json'
    rules=json.loads(rules_path.read_text())['rules']
    policy=load_policy(candidate='A')
    capsule=(ROOT/args.capsule).resolve() if args.capsule else None
    reference_path=(ROOT/args.verify_reference).resolve() if args.verify_reference else None
    if reference_path and not reference_path.is_relative_to(ROOT/'outputs/hybrid_delivery'):
        raise ValueError('Independent reference run required')
    expected=json.loads((reference_path/'report.json').read_text()) if reference_path else None
    write_json(out/'preregistration.json',{
        'scope':'DEV_ONLY_EXPOSED_RESEARCH','policy':policy,'rules_hash':sha(rules_path),
        'rules_limit':'frozen current exchange filters, not historical PIT filters',
        'exit_policy_hash':sha(ROOT/'config/hybrid_exit_research_v1.json'),
        'capsule_manifest_hash':sha(capsule/'capsule.json') if capsule else None,
        'reference_report_hash':sha(reference_path/'report.json') if reference_path else None,
        'source_hashes':{name:sha(ROOT/name) for name in (
            'scripts/replay_multifactor_portfolio.py','kquant_crypto/hybrid_research_portfolio.py',
            'kquant_crypto/candidate_simulation.py','kquant_crypto/hybrid_exit_research.py',
            'kquant_crypto/hybrid_dataset_capsule.py')},
        'boundary':'original common entry calendar ends6h before authorized cutoff; terminal exits disclosed, not a new holding embargo',
        'winner_selection':False,'execution_enabled':False})
    data=load_capsule(capsule) if capsule else load_development(ROOT/'outputs/dual_regime_v1/frozen/data_manifest.json')
    if expected and expected['dataset_hash'] != data.content_hash:
        raise ValueError('Reference dataset mismatch')
    timeline={}; hours={}
    for s,frames in data.bars.items():
        for bar in frames['5m']:
            timeline.setdefault(bar.start,{})[s]=bar
        for bar in frames['1h']:
            hours.setdefault(bar.start+3600,{})[s]=bar
    outputs={}; reference=None
    scenarios=[('REFERENCE',1),('ORIGINAL',1)]+[(c,m) for c in ('FIXED_2_5R','FIXED_3R','T1','T2') for m in (1,2)]
    for candidate,cost in scenarios:
        name=candidate+'_'+str(cost); folder=out/name; folder.mkdir()
        portfolio=CandidatePortfolio(policy,rules) if candidate=='REFERENCE' else ResearchPortfolio(
            policy,rules,exit_candidate=candidate,cost_multiplier=cost)
        trades,equity,result=run(portfolio,timeline,hours,data.manifest['window']['start'],data.cutoff,folder)
        normalized=[{k:t[k] for k in ('symbol','entry_time','exit_time','entry_price','exit_price','quantity','net_pnl','net_r','exit_reason')} for t in trades]
        if candidate=='REFERENCE':
            reference=(normalized,equity)
        if candidate=='ORIGINAL':
            if reference!=(normalized,equity):
                raise ValueError('Original portfolio wrapper parity failed; candidates not run')
        outputs[name]=result
        print(json.dumps({'scenario':name,**{k:v for k,v in result.items() if k!='event_counts'}}),flush=True)
    parity={name:{k:outputs[name][k]==result[k] for k in ('trade_hash','equity_hash')}
            for name,result in expected['scenarios'].items()} if expected else None
    write_json(out/'report.json',{'scope':'DEV_ONLY','original_wrapper_parity':True,
        'reference_parity':parity,
        'dataset_hash':data.content_hash,'scenarios':outputs,'performance':'PERFORMANCE_UNPROVEN',
        'independent_oos':False,'execution_enabled':False})
    if parity and not all(all(checks.values()) for checks in parity.values()):
        raise ValueError('Portable replay differs from frozen reference; inspect without overwriting it')


if __name__=='__main__':
    main()
