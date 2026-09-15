"""Bounded incremental read-only source consumption into independent Hybrid DB.

Current candidate MARKET_QUOTE rows omit source timestamps and size: retained
as unavailable, never promoted to fills. A separate JSONL input permits complete
time-evidenced batches/quotes, with event IDs supplied by the acquisition source.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, UTC
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from kquant_crypto.candidate_policy import load_policy
from kquant_crypto.hybrid_observation import ObservationStore, POLICY


def main():
    p=argparse.ArgumentParser()
    p.add_argument('command',choices=['consume','status','forward','clock-audit'])
    p.add_argument('--database',default='work/hybrid_m2_observation_v2.sqlite3')
    p.add_argument('--input-jsonl')
    p.add_argument('--source-run',default='forward_A_frozen_v1')
    p.add_argument('--limit',type=int,default=500)
    p.add_argument('--output',required=True)
    p.add_argument('--seconds',type=float,default=30)
    args=p.parse_args()
    if not 1 <= args.limit <= 5000: raise ValueError('Bounded batch required')
    output=ROOT/args.output
    if output.exists(): raise ValueError('Do not overwrite observation evidence')
    if args.command=='clock-audit':
        from kquant_crypto.hybrid_public_observer import audit_clock
        report=asyncio.run(audit_clock())
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2))
        return
    policy=load_policy(candidate='A')
    rules=json.loads((ROOT/'outputs/dual_regime_v1/exchange_rules.json').read_text())['rules']
    store=ObservationStore(ROOT/args.database,policy,rules)
    events_before=store.db.execute('SELECT count(*) FROM observer_events').fetchone()[0]
    accepted=duplicates=0
    reasons=Counter()
    failure=None
    if args.command=='forward':
        from kquant_crypto.hybrid_public_observer import observe
        try:
            audits=asyncio.run(observe(store,seconds=args.seconds,lock_path=str(ROOT/args.database)+'.lock'))
            reasons.update(r['reason'] for r in audits if 'reason' in r)
            accepted=sum(reasons.values())
        except Exception as exc:
            failure=type(exc).__name__
    if args.command=='consume':
        if args.input_jsonl:
            events=[json.loads(line) for line in (ROOT/args.input_jsonl).read_text().splitlines() if line]
            pairs=[(r['event_id'],r['event']) for r in events]
        else:
            source=sqlite3.connect((ROOT/'work/candidate_simulation.sqlite3').as_uri()+'?mode=ro',uri=True)
            source.execute('PRAGMA query_only=ON')
            prefix=f'candidate:{args.source_run}:'
            checkpoint=store.db.execute('SELECT max(CAST(substr(id,?) AS INTEGER)) FROM observer_events WHERE substr(id,1,?)=?',
                (len(prefix)+1,len(prefix),prefix)).fetchone()[0]
            if checkpoint is None:
                rows=source.execute("SELECT rowid,payload FROM candidate_records WHERE run_id=? AND kind='events' AND json_extract(payload,'$.kind')='MARKET_QUOTE' ORDER BY rowid DESC LIMIT ?",(args.source_run,args.limit)).fetchall()
                rows.reverse()
            else:
                rows=source.execute("SELECT rowid,payload FROM candidate_records WHERE run_id=? AND rowid>? AND kind='events' AND json_extract(payload,'$.kind')='MARKET_QUOTE' ORDER BY rowid LIMIT ?",(args.source_run,checkpoint,args.limit)).fetchall()
            source.close()
            pairs=[]
            for rowid,payload in rows:
                raw=json.loads(payload)
                event={'type':'quote','symbol':raw['symbol'],'received_at':raw['received_at'],
                       'source_time':raw.get('source_time'),'source_time_basis':raw.get('source_time_basis','NOT_RECORDED'),
                       'bid':raw['bid'],'ask':raw['ask'],'bid_size':raw.get('bid_size'),'ask_size':raw.get('ask_size'),
                       'sequence':raw['sequence'],'source':raw['source'],'venue':'binance','market_type':'spot',
                       'provider_status':'live','source_record_id':raw['event_id'],'source_run':args.source_run}
                pairs.append((f'candidate:{args.source_run}:{rowid}',event))
        for identity,event in pairs:
            result=store.process(identity,event)
            duplicates+=result['duplicate']; accepted+=not result['duplicate']
            reasons.update(r['reason'] for r in result.get('audit',[]) if 'reason' in r)
    state=store.db.execute('SELECT state FROM observer_checkpoint WHERE id=1').fetchone()
    labels=json.loads(state[0])['opportunities'] if state else {}
    report={'at':datetime.now(UTC).isoformat(),'python':sys.executable,'database':str((ROOT/args.database).resolve()),
            'policy':POLICY,'contract_hash':store.contract,'source_hashes':store.code_hashes,
            'new_events':store.db.execute('SELECT count(*) FROM observer_events').fetchone()[0]-events_before,'duplicate_events':duplicates,
            'reasons':dict(reasons),'stored_events':store.db.execute('SELECT count(*) FROM observer_events').fetchone()[0],
            'label_revisions':store.db.execute('SELECT count(*) FROM observer_labels').fetchone()[0],
            'opportunities':len(labels),'fill_statuses':dict(Counter(r['fill_status'] for r in labels.values())),
            'label_statuses':dict(Counter(r['label_status'] for r in labels.values())),
            'actual_exchange_fills':0,'original_writer_modified':False,'training_enabled':False,
            'failure_type':failure,'performance_status':'PERFORMANCE_UNPROVEN',
            'source_bootstrap_scope':'initial_bounded_tail_then_ascending_rowid_checkpoint_not_full_history'}
    store.close()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2,sort_keys=True),encoding='utf-8')
    print(json.dumps(report,indent=2))
    return 1 if failure else 0


if __name__=='__main__':sys.exit(main())
