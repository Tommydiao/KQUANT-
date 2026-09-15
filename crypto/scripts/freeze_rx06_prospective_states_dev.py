"""Freeze genuine opportunity-time pending states; no paths or forced admissions."""
import argparse
from collections import Counter,defaultdict,deque
from dataclasses import asdict
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from replay_multifactor_portfolio import run
from kquant_crypto.candidate_policy import load_policy,digest
from kquant_crypto.hybrid_dataset_capsule import load_capsule
from kquant_crypto.hybrid_dev_fit import sha,write_json
from kquant_crypto.hybrid_research_portfolio import ResearchPortfolio


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    base=ROOT/'outputs/hybrid_delivery';out=(ROOT/a.output).resolve()
    if not out.is_relative_to(base) or out.exists():raise ValueError('New isolated output required')
    source=ROOT/'outputs/hybrid_regime_v1/m2_development_20260905_04/opportunities.jsonl'
    opportunities=[json.loads(s) for s in source.read_text().splitlines()]
    if len(opportunities)!=50 or len({o['economic_signal_id'] for o in opportunities})!=50:
        raise ValueError('Frozen50 identity mismatch')
    bytime=defaultdict(list)
    for o in opportunities:
        bytime[o['signal_time']].append({k:o[k] for k in ('economic_signal_id','symbol','mode','signal_time','plan')})
    old=base/'multifactor_portfolio_20260907_02'
    contract=json.loads((old/'preregistration.json').read_text())
    expected=json.loads((old/'report.json').read_text())
    policy=load_policy(candidate='A');rp=ROOT/'outputs/dual_regime_v1/exchange_rules.json'
    if policy!=contract['policy'] or sha(rp)!=contract['rules_hash']:
        raise ValueError('Frozen policy/rules changed')
    for name in ('kquant_crypto/candidate_simulation.py','kquant_crypto/hybrid_research_portfolio.py','kquant_crypto/hybrid_exit_research.py'):
        if sha(ROOT/name)!=contract['source_hashes'][name]:raise ValueError('Frozen implementation changed')
    rules=json.loads(rp.read_text())['rules'];data=load_capsule(base/'multifactor_dataset_capsule_20260909_01')
    if data.content_hash!=expected['dataset_hash']:raise ValueError('Authorized dataset changed')
    out.mkdir(exist_ok=False)
    write_json(out/'preregistration.json',dict(scope='EXPOSED_DEV_PROSPECTIVE_STATE_FREEZE',
        population='All frozen50 technical opportunities, all3policies; no outcome-based selection',
        source_hash=sha(source),dataset_hash=data.content_hash,policy=policy,
        implementation_hashes={name:sha(ROOT/name) for name in contract['source_hashes']},
        code_hash=sha(Path(__file__)),runtime_enabled=False,new_signals_in_mc=False,
        admissions='Original risk decisions retained; rejected opportunity never forcibly inserted',
        mathematical_target='Existing holdings plus originally admitted pending plans at decision close; not actual fills',
        execution_quality='LEGACY_BAR_PROXY',paths_generated=0))
    timeline={};hours={}
    for s,frames in data.bars.items():
        for b in frames['5m']:timeline.setdefault(b.start,{})[s]=b
        for b in frames['1h']:hours.setdefault(b.start+3600,{})[s]=b
    contexts={};records=[];parity={}
    for candidate in ('ORIGINAL','T1','T2'):
        folder=out/candidate;folder.mkdir();history=deque(maxlen=2017)
        class ObservedPortfolio(ResearchPortfolio):
            def on_closed_batch(self,bars,hourly,now,allow_entries=True):
                before=self.kernels['BTCUSDT'].mode
                super().on_closed_batch(bars,hourly,now,allow_entries)
                history.append(dict(start=now-300,regime_before=before,
                    bars={s:{**asdict(b),'available_at':now,'source_bar_id':f'{s}:{b.start}'} for s,b in bars.items()}))
                if now not in bytime:return
                state=self.snapshot();clone=ResearchPortfolio(policy,rules,exit_candidate=candidate)
                clone.restore(json.loads(json.dumps(state)))
                if digest(clone.snapshot())!=digest(state) or clone.value()!=self.value():
                    raise ValueError('Decision-time restore parity failed')
                file=folder/f'state_{now}.json'
                write_json(file,dict(as_of=now,state=state,nav=self.value()))
                if candidate=='ORIGINAL':
                    hist=list(history);context=out/f'context_{now}.json'
                    write_json(context,dict(as_of=now,history=hist,anchors=dict(self.marks),
                        regime=self.kernels['BTCUSDT'].mode,source_dataset_hash=data.content_hash,
                        first_hour_prefix=[r for r in hist if r['start']>=now//3600*3600],
                        history_contiguous=all(r['start']==hist[0]['start']+i*300 and set(r['bars'])==set(policy['symbols']) for i,r in enumerate(hist)),
                        availability_contract='Historical close proxy; not actual receipt clock'))
                    contexts[now]=dict(file=context.name,hash=sha(context))
                for opportunity in bytime[now]:
                    symbol=opportunity['symbol']
                    events=[e for e in self.events if e['time']==now and e['symbol']==symbol and e['kind'] in ('SIGNAL_RESERVED','ENTRY_REJECTED')]
                    if len(events)!=1:raise ValueError('Missing/ambiguous original admission')
                    event=events[0];pending=self.pending.get(symbol)
                    accepted=event['kind']=='SIGNAL_RESERVED'
                    if accepted and (pending is None or pending['signal_time']!=now):
                        raise ValueError('Accepted proposal not pending at decision')
                    if accepted and symbol in self.positions:raise ValueError('Proposal already filled at signal time')
                    records.append(dict(**opportunity,policy=candidate,admitted=accepted,
                        reason=event.get('reason'),decision_event_id=event['event_id'],
                        snapshot_file=str(file.relative_to(out)),snapshot_hash=sha(file),
                        context=contexts[now],fill_status='PENDING_NOT_FILLED' if accepted else 'REJECTED',
                        prior_position_count=len(self.positions),all_pending_count=len(self.pending)))
        portfolio=ObservedPortfolio(policy,rules,exit_candidate=candidate)
        _,_,result=run(portfolio,timeline,hours,data.manifest['window']['start'],data.cutoff,folder)
        parity[candidate]=all(result[k]==expected['scenarios'][candidate+'_1'][k] for k in ('trade_hash','equity_hash'))
        if not parity[candidate]:raise ValueError('Observed replay differs from frozen portfolio')
    if len(records)!=150:raise ValueError('Incomplete opportunity-policy population')
    write_json(out/'state_index.json',records)
    counts={c:dict(Counter(r['fill_status'] if r['admitted'] else 'REJECTED:'+str(r['reason']) for r in records if r['policy']==c)) for c in parity}
    write_json(out/'report.json',dict(scope='EXPOSED_DEV_PENDING_STATE_COVERAGE',counts=counts,
        parity=parity,records=len(records),context_count=len(contexts),index_hash=sha(out/'state_index.json'),
        paths_generated=0,admission_changed=False,runtime_enabled=False,
        limitation='State freeze only. Partial first-hour history must seed any future path replay; no quote-aware evidence, probabilistic gate or forced rejected-plan exposure.'))
    print(json.dumps(dict(records=len(records),counts=counts,all_replay_hashes_match=all(parity.values()))))


if __name__=='__main__':main()
