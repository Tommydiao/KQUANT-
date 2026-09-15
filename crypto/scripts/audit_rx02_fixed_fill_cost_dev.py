"""Separate frozen-fill fee sensitivity from full capital-constrained reruns."""
import argparse
import json
import math
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha,write_json
from kquant_crypto.hybrid_fixed_fill_cost import reprice_fixed_fill,summary
from kquant_crypto.hybrid_entry_attribution import opportunity_key


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True)
    p.add_argument('--original-stress',help='Explicit independently produced ORIGINAL stress trades JSONL')
    a=p.parse_args()
    base=ROOT/'outputs/hybrid_delivery';out=(ROOT/a.output).resolve()
    if not out.is_relative_to(base) or out.exists():raise ValueError('New isolated output required')
    rows=[];results={};hashes={}
    for candidate in ('ORIGINAL','T1','T2'):
        folder=base/'multifactor_portfolio_20260907_02'
        source=folder/(candidate+'_1')/'trades.jsonl';hashes[str(source.relative_to(ROOT))]=sha(source)
        trades=[json.loads(s) for s in source.read_text().splitlines()]
        scenarios={}
        for m in (1,2):
            repriced=[dict(candidate=candidate,**reprice_fixed_fill(t,m)) for t in trades]
            rows.extend(repriced);scenarios[str(m)]=summary(repriced)
        stress=folder/(candidate+'_2')/'trades.jsonl'
        if candidate=='ORIGINAL' and a.original_stress:
            stress=(ROOT/a.original_stress).resolve()
            if not stress.is_relative_to(base):raise ValueError('Independent evidence source required')
        full=None
        if stress.exists():
            hashes[str(stress.relative_to(ROOT))]=sha(stress)
            full=[json.loads(s) for s in stress.read_text().splitlines()]
            if any(r['cost_multiplier']!=2 or r['execution_source']!='ohlcv' for r in full):
                raise ValueError('Expected double-cost historical proxy trades')
        results[candidate]=dict(fixed_fills=scenarios,
            full_stress_source_status='AVAILABLE' if full is not None else 'MISSING_SOURCE',
            full_stress_expected_source=str(stress.relative_to(ROOT)),
            full_stress_replay_trades=len(full) if full is not None else None,
            full_stress_replay_net_pnl=sum(r['net_pnl'] for r in full) if full is not None else None,
            full_stress_not_repriced_or_merged=True)
        if full is not None:
            original={opportunity_key(t):t for t in trades}
            stressed={opportunity_key(t):t for t in full}
            if len(original)!=len(trades) or len(stressed)!=len(full):
                raise ValueError('Duplicate economic opportunity')
            paired=[]
            for key in sorted(original.keys() & stressed.keys()):
                b,s=original[key],stressed[key];fixed=reprice_fixed_fill(b,2)
                unchanged=all(b[k]==s[k] for k in ('entry_time','exit_time','entry_market_reference','exit_market_reference','exit_reason'))
                unit=fixed['net_pnl']/b['quantity']
                quantity_effect=(s['quantity']-b['quantity'])*unit
                remainder=s['net_pnl']-fixed['net_pnl']-quantity_effect
                if unchanged and not math.isclose(remainder,0,abs_tol=1e-7):
                    raise ValueError('Same-timing quantity bridge failed')
                paired.append(dict(economic_key=key,quantity_ratio=s['quantity']/b['quantity'],
                    timing_references_reason_unchanged=unchanged,quantity_effect=quantity_effect,
                    remaining_cash_difference=remainder))
            results[candidate]['stress_bridge']=dict(pairs=paired,
                baseline_only=[list(k) for k in sorted(original.keys()-stressed.keys())],
                stress_only=[list(k) for k in sorted(stressed.keys()-original.keys())],
                interpretation='Algebraic fixed-BASE-quantity decomposition, not causal prediction advantage')
    if any(sha(ROOT/name)!=digest for name,digest in hashes.items()):
        raise ValueError('Source changed during audit')
    out.mkdir(exist_ok=False)
    with (out/'fixed_fill_costs.jsonl').open('x',encoding='utf-8') as f:
        for r in rows:f.write(json.dumps(r,allow_nan=False)+'\n')
    report=dict(scope='EXPOSED_DEV_FIXED_FILL_COST_ATTRIBUTION',results=results,source_hashes=hashes,
        rows_hash=sha(out/'fixed_fill_costs.jsonl'),code_hash=sha(Path(__file__)),
        helper_hash=sha(ROOT/'kquant_crypto/hybrid_fixed_fill_cost.py'),execution_enabled=False,
        limitation='Costed counterfactual on unchanged timing/quantity, not a capital-constrained replay or an executable return claim. Full stress rerun is a separate original source.')
    write_json(out/'report.json',report);print(json.dumps(results))


if __name__=='__main__':main()
