"""Frozen opportunity audit: no synthetic fills, labels, or restricted data reads."""
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_entry_attribution import classify_opportunity


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    out=(ROOT/a.output).resolve()
    if not out.is_relative_to(ROOT/'outputs/hybrid_delivery') or out.exists():
        raise ValueError('New independent output required')
    m2=ROOT/'outputs/hybrid_regime_v1/m2_development_20260905_04'
    portfolio=ROOT/'outputs/hybrid_delivery/multifactor_portfolio_20260907_02'
    fingerprints={}
    def read(path):
        raw=path.read_bytes();fingerprints[str(path.relative_to(ROOT))]=hashlib.sha256(raw).hexdigest()
        return [json.loads(line) for line in raw.decode('utf-8').splitlines()]
    opportunities=read(m2/'opportunities.jsonl');labels=read(m2/'labels.jsonl');partitions=read(m2/'partitions.jsonl')
    def index(rows):
        values={row['economic_signal_id']:row for row in rows}
        if len(values)!=len(rows):raise ValueError('Duplicate economic signal')
        return values
    oi,li,pi=map(index,(opportunities,labels,partitions))
    if set(oi)!=set(li) or set(oi)!=set(pi):raise ValueError('M2 identity mismatch')
    rows=[];policies={}
    for scenario in ('ORIGINAL_1','T1_1','T2_1'):
        events=read(portfolio/scenario/'events.jsonl');trades=read(portfolio/scenario/'trades.jsonl')
        decisions=[e for e in events if e['kind'] in ('SIGNAL_RESERVED','ENTRY_REJECTED')]
        original_keys={(o['symbol'],o['signal_time']) for o in opportunities}
        extras=[e for e in decisions if (e['symbol'],e['time']) not in original_keys]
        if extras:raise ValueError('Policy has additional unaccounted technical opportunities')
        for opportunity in opportunities:
            sid=opportunity['economic_signal_id'];label=li[sid]
            state=classify_opportunity(opportunity,label if scenario=='ORIGINAL_1' else None,events,trades)
            if scenario=='ORIGINAL_1' and (state['fill_status']=='FILLED_VIRTUAL') != (label['status']=='mature'):
                raise ValueError('Baseline label/fill disagreement')
            rows.append(dict(economic_signal_id=sid,scenario=scenario,symbol=opportunity['symbol'],mode=opportunity['mode'],
                signal_time=opportunity['signal_time'],utc_date=datetime.fromtimestamp(opportunity['signal_time'],timezone.utc).date().isoformat(),
                policy_hash=next(e['policy_hash'] for e in decisions),
                baseline_label_source=label['source'],baseline_label_status=label['status'],
                baseline_label_available_at=label['available_at'],baseline_partition=pi[sid]['partition'],
                baseline_partition_exclusion=pi[sid]['exclusion_reason'],
                partition_reused_for_training=False,counterfactual_generated=False,**state))
        selected=[r for r in rows if r['scenario']==scenario]
        policies[scenario]=dict(opportunities=len(selected),attemptable=sum(e['kind']=='SIGNAL_RESERVED' for e in decisions),
            fill_status=dict(Counter(r['fill_status'] for r in selected)),label_status=dict(Counter(r['label_status'] for r in selected)),
            rejection_reasons=dict(Counter(r['reason'] for r in selected if r['fill_status']=='NOT_FILLED')))
    strata=defaultdict(Counter)
    for row in rows:
        key=(row['scenario'],row['symbol'],row['mode'],row['utc_date'])
        strata[key][row['fill_status']]+=1
    out.mkdir(parents=True,exist_ok=False)
    with (out/'opportunity_states.jsonl').open('x',encoding='utf-8') as handle:
        for row in rows:handle.write(json.dumps(row,allow_nan=False)+'\n')
    result=dict(scope='DEV_ONLY',status='RX02_FUNNEL_COMPLETE_OTHER_ATTRIBUTION_PENDING',execution_enabled=False,
        policies=policies,strata=[dict(scenario=k[0],symbol=k[1],mode=k[2],date=k[3],counts=dict(v)) for k,v in sorted(strata.items())],
        original_partitions=dict(Counter(r['partition'] for r in partitions)),
        original_eligible_partitions=dict(Counter(r['partition'] for r in partitions if r['population_eligible'] and r['exclusion_reason'] is None)),
        original_exclusions=dict(Counter(str(r['exclusion_reason']) for r in partitions)),
        counterfactual_labels_generated=0,inputs=fingerprints,
        inputs_unchanged=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==value for name,value in fingerprints.items()),
        limitations=['Frozen 50 original-A path technical opportunities, not every possible market-time opportunity',
                    'Legacy unavailable labels retain end-of-dataset information_end; not evidence of pending positions',
                    'Legacy partitions audited only; not approved new long-holding purge/embargo',
                    'No first-touch or unfilled counterfactual outcome simulation in this audit'])
    (out/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(dict(policies=policies,partitions=result['original_partitions'],eligible_partitions=result['original_eligible_partitions'],exclusions=result['original_exclusions'],inputs_unchanged=result['inputs_unchanged'])))


if __name__=='__main__':main()
