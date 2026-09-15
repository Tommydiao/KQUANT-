"""Freeze matched reference identities before any matched-outcome calculation."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_dataset_capsule import load_capsule
from kquant_crypto.hybrid_dev_fit import sha,write_json
from kquant_crypto.hybrid_reference_matching import select_reference
from kquant_crypto.strategy_dual_mode_v1 import DualRegimeKernel


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args();out=(ROOT/a.output).resolve()
    if not out.is_relative_to(ROOT/'outputs/hybrid_delivery') or out.exists():raise ValueError('New output required')
    contract=ROOT/'config/rx05_entry_edge_attribution_01.json'
    config=json.loads(contract.read_text())
    if config['reference_selection']['version']!='PAST7D_SAME_SYMBOL_MODE_OFFSET_V1':raise ValueError('Unregistered matching rule')
    source=ROOT/'outputs/hybrid_regime_v1/m2_development_20260905_04/opportunities.jsonl'
    opportunities=[json.loads(l) for l in source.read_text().splitlines()]
    capsule=ROOT/'outputs/hybrid_delivery/multifactor_dataset_capsule_20260909_01'
    data=load_capsule(capsule);snapshots={};by_symbol={}
    for symbol,frames in data.bars.items():
        kernel=DualRegimeKernel('A');hourly={b.start+3600:b for b in frames['1h']};last_hour=None;selected=[]
        for bar in frames['5m']:
            now=bar.start+300;hour=hourly.get(now);kernel.on_bar(bar,hour)
            if hour:last_hour=hour
            if now<data.manifest['window']['start'] or not kernel.ready or not last_hour:continue
            if now-last_hour.start-3600>=3600:continue
            row=dict(symbol=symbol,as_of=now,available_at=now,mode=kernel.mode,
                atr_fraction=kernel.hour.atr/last_hour.close,hour_closed_at=last_hour.start+3600,
                hour_close=last_hour.close,availability_basis='ASSUMED_CLOSE_LEGACY_BAR_PROXY')
            snapshots[symbol,now]=row;selected.append(row)
        by_symbol[symbol]=selected
    excluded={(r['symbol'],r['signal_time']) for r in opportunities};matches=[]
    for opportunity in opportunities:
        key=opportunity['symbol'],opportunity['signal_time']
        if key not in snapshots:raise ValueError('Original signal snapshot unavailable')
        signal=dict(snapshots[key],economic_signal_id=opportunity['economic_signal_id'])
        if signal['mode']!=opportunity['mode']:raise ValueError('Signal regime replay mismatch')
        match=select_reference(signal,by_symbol[opportunity['symbol']],excluded)
        matches.append(dict(economic_signal_id=signal['economic_signal_id'],signal=signal,**match))
    out.mkdir(parents=True,exist_ok=False)
    with (out/'reference_selection.jsonl').open('x',encoding='utf-8') as f:
        for row in matches:f.write(json.dumps(row,allow_nan=False)+'\n')
    usage=Counter((r['reference']['symbol'],r['reference']['as_of']) for r in matches if r['reference'])
    result=dict(scope='DEV_ONLY',status_counts=dict(Counter(r['status'] for r in matches)),
        reference_reuse=[dict(symbol=k[0],as_of=k[1],uses=v) for k,v in usage.items() if v>1],
        source_hash=sha(source),policy_hash=sha(contract),dataset_hash=data.content_hash,
        selection_hash=sha(out/'reference_selection.jsonl'),
        code_hashes={str(path.relative_to(ROOT)):sha(path) for path in (Path(__file__),ROOT/'kquant_crypto/hybrid_reference_matching.py')},
        outcomes_read=False,training_enabled=False,execution_enabled=False,
        limitations=['Only assumed-close historical availability','Past-window references may reuse or overlap; not independent controls','No outcomes yet; no profitability conclusion'])
    write_json(out/'report.json',result);print(json.dumps(result))


if __name__=='__main__':main()
