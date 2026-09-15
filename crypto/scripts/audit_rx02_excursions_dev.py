"""Actual authorized capsule excursion audit; no future-price strategy edits."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_dataset_capsule import load_capsule
from kquant_crypto.hybrid_dev_fit import sha,write_json
from kquant_crypto.hybrid_excursion_audit import audit_excursion


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    out=(ROOT/a.output).resolve()
    if not out.is_relative_to(ROOT/'outputs/hybrid_delivery') or out.exists():raise ValueError('New independent output required')
    source=ROOT/'outputs/hybrid_delivery/multifactor_portfolio_20260907_02'
    capsule=ROOT/'outputs/hybrid_delivery/multifactor_dataset_capsule_20260909_01'
    report=json.loads((source/'report.json').read_text());data=load_capsule(capsule)
    if data.content_hash!=report['dataset_hash']:raise ValueError('Dataset mismatch')
    out.mkdir(parents=True,exist_ok=False)
    inputs={str(source.relative_to(ROOT))+'/report.json':sha(source/'report.json'),
            str(capsule.relative_to(ROOT))+'/capsule.json':sha(capsule/'capsule.json')}
    summary={}
    with (out/'trade_excursions.jsonl').open('x',encoding='utf-8') as stream:
        for scenario in ('ORIGINAL_1','FIXED_2_5R_1','FIXED_3R_1','T1_1','T2_1'):
            path=source/scenario/'trades.jsonl'
            if sha(path)!=report['scenarios'][scenario]['trade_hash']:raise ValueError('Trade hash mismatch')
            inputs[str(path.relative_to(ROOT))]=sha(path)
            rows=[]
            for line in path.read_text().splitlines():
                trade=json.loads(line);row=audit_excursion(trade,data.bars[trade['symbol']]['5m'],data.cutoff)
                row.update(scenario=scenario,symbol=trade['symbol'],mode=trade['mode'],trade_id=trade['trade_id'],signal_time=trade['signal_time'])
                rows.append(row);stream.write(json.dumps(row,allow_nan=False)+'\n')
            summary[scenario]=dict(trades=len(rows),status=dict(Counter(r['status'] for r in rows)),
                touch_status=dict(Counter(r.get('target_touch_status') for r in rows)),
                positive_observed_net_mfe=sum(r.get('net_mfe_observed') is not None and r['net_mfe_observed']>0 for r in rows),
                excluded_exit_bars=sum(r.get('exit_bar_extrema_excluded',False) for r in rows))
    result=dict(scope='DEV_ONLY',execution_enabled=False,summary=summary,inputs=inputs,
        inputs_unchanged=all(sha(ROOT/name)==value for name,value in inputs.items()),
        rows_hash=sha(out/'trade_excursions.jsonl'),code_hashes={str(p.relative_to(ROOT)):sha(p) for p in (Path(__file__),ROOT/'kquant_crypto/hybrid_excursion_audit.py')},
        limitations=['OHLC interval timing only; no invented tick chronology','Protective exit bar extrema excluded because later prices may be post-exit','Observed maxima are posthoc diagnostics, not realizable exit policies'])
    write_json(out/'report.json',result);print(json.dumps(summary))


if __name__=='__main__':main()
