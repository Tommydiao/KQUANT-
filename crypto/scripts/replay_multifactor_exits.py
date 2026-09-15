"""Fixed original entries: paired exit research, not a capital-constrained portfolio."""
import argparse
from bisect import bisect_left
from collections import defaultdict
import json
from pathlib import Path
import sys
import math

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_dev_fit import audit,CONFIG,DATA,sha,write_json
from kquant_crypto.hybrid_dataset import load_development
from kquant_crypto.strategy_dual_mode_v1 import DualRegimeKernel
from kquant_crypto.hybrid_exit_research import structural_exit,net_target_reference
from kquant_crypto.hybrid_exit_bar import exit_on_bar,realized_net_r
from kquant_crypto.hybrid_exit_metrics import summarize


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    out=(ROOT/parser.parse_args().output).resolve()
    if not out.is_relative_to(ROOT/'outputs/hybrid_delivery'):
        raise ValueError('Independent output required')
    out.mkdir(exist_ok=False)
    policy=ROOT/'config/hybrid_exit_research_v1.json'
    write_json(out/'preregistration.json',{'scope':'DEV_ONLY_EXPOSED_RESEARCH',
        'policy':json.loads(policy.read_text()),'policy_hash':sha(policy),'code_hash':sha(Path(__file__)),
        'selection':'A27 original executed entries only; fixed quantity/risk; no capital-competition claim',
        'model_used':False,'execution_enabled':False})
    selected,checks=audit(json.loads(CONFIG.read_text()))
    data=load_development(ROOT/'outputs/dual_regime_v1/frozen/data_manifest.json')
    opportunities={r['economic_signal_id']:r for r in map(json.loads,(DATA/'opportunities.jsonl').read_text().splitlines())}
    contexts={}
    for symbol,frames in data.bars.items():
        kernel=DualRegimeKernel('A')
        hourly={b.start+3600:b for b in frames['1h']}
        history=[]
        context={}
        for bar in frames['5m']:
            now=bar.start+300
            hour=hourly.get(now)
            result=kernel.on_bar(bar,hour)
            if hour:
                history=(history+[hour])[-7:]
            context[now]={'mode_invalidated':result.get('mode_invalidated',False),
                          'hours':list(history) if hour else None,'atr':kernel.hour.atr}
        contexts[symbol]=context
    output=[]
    for item in selected:
        label=item['label']; trade=label['executed_trade']
        plan=opportunities[label['economic_signal_id']]['plan']
        symbol=label['symbol']; bars=data.bars[symbol]['5m']
        start=bisect_left([b.start for b in bars],trade['entry_time'])
        for candidate in ('ORIGINAL','FIXED_2_5R','FIXED_3R','T1','T2'):
            # Preserve range exactly; new structural policies only concern trend.
            effective=candidate if label['mode']=='UP_TREND' else 'ORIGINAL'
            stop=plan['stop']; target=plan['target']; pending=None; outcome=None
            if effective.startswith('FIXED'):
                target=net_target_reference(trade['entry_price'],trade['unit_net_risk'],2.5 if effective=='FIXED_2_5R' else 3.)
            if effective in ('T1','T2'):
                target=None
            for i in range(start,len(bars)):
                bar=bars[i]
                if i>start and bar.start!=bars[i-1].start+300:
                    outcome=(None,bar.start,'CENSORED_DATA_GAP'); break
                outcome=exit_on_bar(bar,stop,target,pending)
                if outcome:
                    break
                now=bar.start+300; context=contexts[symbol][now]
                if effective in ('T1','T2'):
                    if context['hours']:
                        decision=structural_exit(effective,'UP_TREND',context['hours'],now,stop,context['atr'])
                        if decision['exit_next_bar']:
                            pending='structure_invalidated'
                        stop=decision['stop_next_bar']
                else:
                    if (i-start+1)>=(72 if label['mode']=='UP_TREND' else 36):
                        pending='timeout'
                    if context['mode_invalidated']:
                        pending='mode_invalidated'
            if outcome is None:
                outcome=(bars[-1].close,bars[-1].start+300,'terminal_liquidation')
            reference,exit_time,reason=outcome
            net=realized_net_r(trade['entry_price'],reference,trade['unit_net_risk']) if reference is not None else None
            row={'candidate':candidate,'effective_policy':effective,'symbol':symbol,'mode':label['mode'],
                 'trade_id':trade['trade_id'],'entry_time':trade['entry_time'],'exit_time':exit_time,
                 'exit_reason':reason,'net_r':net,'holding_seconds':exit_time-trade['entry_time'],
                 'source_label_hash':label['label_hash'],'counterfactual':candidate!='ORIGINAL'}
            row.update(entry_price=trade['entry_price'],exit_reference=reference,
                       base_unit_risk=trade['unit_net_risk'],
                       fixed_path_stress_net_r=realized_net_r(
                           trade['entry_price']/1.0005*1.001,reference,trade['unit_net_risk'],2)
                           if reference is not None else None,
                       stress_scope='SAME_PATH_COST_RECOUNT_NOT_FULL_STRESS_REPLAY')
            if candidate=='ORIGINAL':
                row['baseline_match']=exit_time==trade['exit_time'] and reason==trade['exit_reason'] and math.isclose(net, label['net_r'],abs_tol=1e-8)
            output.append(row)
    with (out/'trades.jsonl').open('x',encoding='utf-8') as handle:
        for row in output:
            handle.write(json.dumps(row,sort_keys=True,allow_nan=False)+'\n')
    baseline=[r for r in output if r['candidate']=='ORIGINAL']
    matches=sum(r['baseline_match'] for r in baseline)
    result={'scope':'DEV_ONLY','baseline_matches':matches,'baseline_count':len(baseline),
            'status':'PAIRED_RESEARCH_ONLY' if matches==len(baseline) else 'BASELINE_MISMATCH_BLOCKED',
            'portfolio_validated':False,'performance':'PERFORMANCE_UNPROVEN',
            'trades_hash':sha(out/'trades.jsonl'),'dataset_hash':data.content_hash}
    result['policy_metrics']={name:summarize([r for r in output if r['candidate']==name])
                             for name in ('ORIGINAL','FIXED_2_5R','FIXED_3R','T1','T2')}
    grouped=defaultdict(list)
    for row in output:
        grouped[row['candidate']+':'+row['symbol']+':'+row['mode']].append(row)
    result['symbol_mode_metrics']={k:summarize(v) for k,v in grouped.items()}
    write_json(out/'report.json',result)
    print(json.dumps(result))


if __name__=='__main__':
    main()
