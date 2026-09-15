"""Explain actual frozen portfolio rejections from their preceding events."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.hybrid_entry_attribution import rejection_occupancy


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    out=(ROOT/a.output).resolve()
    if not out.is_relative_to(ROOT/'outputs/hybrid_delivery') or out.exists():
        raise ValueError('New research output required')
    source=ROOT/'outputs/hybrid_delivery/multifactor_portfolio_20260907_02'
    result={};fingerprints={}
    for scenario in ('ORIGINAL_1','T1_1','T2_1'):
        path=source/scenario/'events.jsonl';raw=path.read_bytes()
        fingerprints[str(path.relative_to(ROOT))]=hashlib.sha256(raw).hexdigest()
        result[scenario]=rejection_occupancy([json.loads(line) for line in raw.decode().splitlines()])
    out.mkdir(parents=True,exist_ok=False)
    payload=dict(scope='DEV_ONLY',execution_enabled=False,scenarios=result,inputs=fingerprints,
        inputs_unchanged=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==value for name,value in fingerprints.items()),
        limitations=['Historical virtual event chronology, not exchange events','Occupancy is descriptive; not a new candidate selection rule'])
    (out/'report.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
    print(json.dumps({name:dict(rejections=len(r['rejections']),supported=sum(e['prior_event_support'] is True for e in r['rejections']),
                              open_positions=len(r['remaining_positions']),pending=len(r['remaining_pending'])) for name,r in result.items()}))


if __name__=='__main__':main()
