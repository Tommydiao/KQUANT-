"""Frozen50 hypothetical unit outcomes, separate from actual portfolio trades."""
import argparse
from bisect import bisect_left
from collections import Counter
import json
import math
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_dataset_capsule import load_capsule
from kquant_crypto.hybrid_dev_fit import sha,write_json
from kquant_crypto.strategy_dual_mode_v1 import DualRegimeKernel
from kquant_crypto.hybrid_exit_research import structural_exit
from kquant_crypto.hybrid_exit_bar import exit_on_bar,realized_net_r


def resolve(opportunity,candidate,bars,contexts,cutoff):
    plan=opportunity['plan'];signal=opportunity['signal_time']
    index=bisect_left([b.start for b in bars],signal)
    base=dict(economic_signal_id=opportunity['economic_signal_id'],candidate=candidate,
        symbol=opportunity['symbol'],mode=opportunity['mode'],signal_time=signal,
        counterfactual=True,reference_quantity=1,base_unit_risk=plan['unit_net_risk'],
        execution_quality='LEGACY_BAR_PROXY',training_enabled=False)
    if index==len(bars) or bars[index].start!=signal:
        return dict(base,status='UNAVAILABLE',reason='MISSING_NEXT_BAR',net_r=None)
    effective=candidate if opportunity['mode']=='UP_TREND' else 'ORIGINAL'
    entry=bars[index].open*1.0005;stop=plan['stop'];target=plan['target'] if effective=='ORIGINAL' else None
    pending=None;outcome=None
    # Accepted legacy entries that gap across protection exit immediately.
    if entry<=stop:outcome=(bars[index].open,signal,'entry_gap_stop')
    elif target is not None and entry>=target:outcome=(bars[index].open,signal,'entry_gap_target')
    if outcome is None:
        for i in range(index,len(bars)):
            bar=bars[i]
            if i>index and bar.start!=bars[i-1].start+300:
                return dict(base,status='CENSORED',reason='DATA_GAP',net_r=None)
            outcome=exit_on_bar(bar,stop,target,pending)
            if outcome:break
            now=bar.start+300;context=contexts[now]
            if effective in ('T1','T2'):
                if context['hours']:
                    decision=structural_exit(effective,'UP_TREND',context['hours'],now,stop,context['atr'])
                    if decision['exit_next_bar']:pending='structure_invalidated'
                    stop=decision['stop_next_bar']
            else:
                if i-index+1 >= (72 if opportunity['mode']=='UP_TREND' else 36):pending='timeout'
                if context['mode_invalidated']:pending='mode_invalidated'
    if outcome is None:outcome=(bars[-1].close,bars[-1].start+300,'terminal_liquidation')
    price,time,reason=outcome
    if time>cutoff:raise ValueError('Outcome outside authorized boundary')
    return dict(base,status='MATURE',entry_price=entry,exit_reference=price,entry_time=signal,exit_time=time,
        label_available_at=min(cutoff,((time//300)+1)*300),reason=reason,
        net_r=realized_net_r(entry,price,plan['unit_net_risk']),holding_seconds=time-signal)


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();out=(ROOT/a.output).resolve()
    if not out.is_relative_to(ROOT/'outputs/hybrid_delivery') or out.exists():raise ValueError('New output required')
    config=ROOT/'config/rx02_fixed_opportunity_outcomes_v1.json'
    contract=json.loads(config.read_text());m2=ROOT/'outputs/hybrid_regime_v1/m2_development_20260905_04'
    opportunities=[json.loads(l) for l in (m2/'opportunities.jsonl').read_text().splitlines()]
    labels={r['economic_signal_id']:r for r in map(json.loads,(m2/'labels.jsonl').read_text().splitlines())}
    if len(opportunities)!=50 or len(labels)!=50:raise ValueError('Frozen50 required')
    out.mkdir(parents=True,exist_ok=False)
    inputs={str(p.relative_to(ROOT)):sha(p) for p in (config,m2/'opportunities.jsonl',m2/'labels.jsonl')}
    write_json(out/'preregistration.json',dict(contract=contract,inputs=inputs,code_hash=sha(Path(__file__))))
    data=load_capsule(ROOT/'outputs/hybrid_delivery/multifactor_dataset_capsule_20260909_01');contexts={}
    for symbol,frames in data.bars.items():
        kernel=DualRegimeKernel('A');hourly={b.start+3600:b for b in frames['1h']};history=[];context={}
        for bar in frames['5m']:
            now=bar.start+300;hour=hourly.get(now);decision=kernel.on_bar(bar,hour)
            if hour:history=(history+[hour])[-7:]
            context[now]=dict(mode_invalidated=decision.get('mode_invalidated',False),hours=list(history) if hour else None,atr=kernel.hour.atr)
        contexts[symbol]=context
    rows=[];matches=0
    for opportunity in opportunities:
        label=labels[opportunity['economic_signal_id']]
        for candidate in contract['candidates']:
            row=resolve(opportunity,candidate,data.bars[opportunity['symbol']]['5m'],contexts[opportunity['symbol']],data.cutoff)
            row['original_fill_status']='FILLED_VIRTUAL' if label['status']=='mature' else 'NOT_FILLED'
            if candidate=='ORIGINAL' and label['status']=='mature':
                t=label['executed_trade']
                row['baseline_match']=row['status']=='MATURE' and row['exit_time']==t['exit_time'] and row['reason']==t['exit_reason'] and math.isclose(row['net_r'],label['net_r'],abs_tol=1e-8)
                matches+=row['baseline_match']
            rows.append(row)
    with (out/'counterfactual_outcomes.jsonl').open('x',encoding='utf-8') as handle:
        for row in rows:handle.write(json.dumps(row,allow_nan=False)+'\n')
    result=dict(scope='DEV_ONLY',baseline_matches=matches,baseline_required=27,
        status='PAIRED_UNIT_RESEARCH_ONLY' if matches==27 else 'BASELINE_MISMATCH_BLOCKED',
        counts=dict(Counter(r['candidate']+':'+r['original_fill_status']+':'+r['status'] for r in rows)),
        rows_hash=sha(out/'counterfactual_outcomes.jsonl'),dataset_hash=data.content_hash,
        execution_enabled=False,training_enabled=False,portfolio_performance=False,
        inputs_unchanged=all(sha(ROOT/name)==value for name,value in inputs.items()))
    write_json(out/'report.json',result);print(json.dumps(result))
    if matches!=27:raise SystemExit(1)


if __name__=='__main__':main()
