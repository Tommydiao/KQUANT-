"""M2 offline build. Never reads sealed market rows or writes original stores."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from kquant_crypto.candidate_policy import digest
from kquant_crypto.candidate_simulation import CandidatePortfolio
from kquant_crypto.hybrid_dataset import load_development, file_hash, SYMBOLS
from kquant_crypto.hybrid_features import snapshot, FEATURE_SCHEMA
from kquant_crypto.hybrid_labels import from_opportunity, delayed_open_assessment, LABEL_SCHEMA
from kquant_crypto.hybrid_partitions import partition_policy, assign_partitions


def write_json(path, value):
    with path.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)


def write_rows(path, rows):
    with path.open('x',encoding='utf-8') as stream:
        for row in rows:
            stream.write(json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n')


def record_hash(rows,key):
    import hashlib
    h=hashlib.sha256()
    for row in sorted(rows,key=lambda r:str(r[key])):
        h.update(json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
        h.update(b'\n')
    return h.hexdigest()


def collect(portfolio, dataset):
    window=dataset.manifest['window']; start=window['start']; end=dataset.cutoff
    timeline={}; hours={}
    for symbol,series in dataset.bars.items():
        for bar in series['5m']:
            timeline.setdefault(bar.start,{})[symbol]=bar
        for bar in series['1h']:
            hours.setdefault(bar.start+3600,{})[symbol]=bar
    features=[]; opportunities=[]; delayed=[]
    for stamp,bars in sorted(timeline.items()):
        now=stamp+300
        complete=set(bars)==set(SYMBOLS)
        allow=start<=now<=end-21600 and complete
        before=len(portfolio.events)
        portfolio.on_closed_batch(bars,hours.get(now,{}),now,allow_entries=allow)
        emitted=portfolio.events[before:]
        if now<start:
            continue
        for symbol in SYMBOLS:
            if symbol not in bars or not portfolio.decisions[symbol].get('signal'):
                continue
            # New entries require the aligned universe; existing protection is
            # still processed above for every individually valid symbol.
            feature=snapshot(portfolio,symbol,available_at=now)
            feature['provenance']={tf:dataset.provenance[symbol][tf].get(t) for tf,t in
                (('5m',stamp),('1h',portfolio.kernels[symbol].hour_bars[-1].start))}
            features.append(feature)
            reason=[e.get('reason',e['kind']) for e in emitted if e['symbol']==symbol and e['kind'] in
                    ('ENTRY_REJECTED','ENTRY_CANCELED','SIGNAL_RESERVED','SIGNAL_NOT_TRADED')]
            if not allow:
                reason.append('outside_original_new_entry_window')
            if not complete:
                reason.append('incomplete_symbol_batch')
            signal=portfolio.decisions[symbol]['signal']
            opportunities.append({k:feature[k] for k in ('economic_signal_id','symbol','mode','signal_time','snapshot_hash')} |
                {'original_reasons':reason,'original_trade_id':digest([portfolio.policy['policy_hash'],symbol,signal['mode'],now]),
                 'plan':signal,'run':'dev_A_base_v4','source_population':'original_A_portfolio_path_candidates'})
            delayed.append({'economic_signal_id':feature['economic_signal_id'],'signal_time':now,
                'completed_at':now+4,'expires_at':now+30,'next_open':now+300,
                'latency_basis':'synthetic_4s_diagnostic_not_measured_or_admitted',
                **delayed_open_assessment(now,completed_at=now+4,expires_at=now+30,next_open=now+300)})
    portfolio.finish(end)
    records=portfolio.drain()
    records['equity']=[r for r in records['equity'] if r['time']>=start]
    trade_by_id={r['trade_id']:r for r in records['trades']}
    labels=[from_opportunity(o,trade_by_id.get(o['original_trade_id']),cutoff=end) for o in opportunities]
    return features,opportunities,labels,delayed,records


def build(output):
    started=time.perf_counter()
    output=Path(output).resolve()
    base=(ROOT/'outputs/hybrid_regime_v1').resolve()
    if not output.is_relative_to(base) or output==base:
        raise ValueError('New isolated Hybrid output required')
    output.mkdir(parents=True,exist_ok=False)
    path=ROOT/'outputs/dual_regime_v1/frozen/data_manifest.json'
    window=json.loads(path.read_text(encoding='utf-8'))['window']
    split_policy=partition_policy(window['start'],window['start']+int(window['days']*.7)*86400)
    # Register population/feature/clock definitions before loading market rows.
    contract={'version':'hybrid_m2_build_v1','candidate':'A','label_schema':LABEL_SCHEMA,'feature_schema':FEATURE_SCHEMA,
              'delayed_diagnostic':{'completion_seconds':4,'ttl_seconds':30,'actual_fills':False},
              'partition_policy':split_policy,'training_enabled':False,'filtering_enabled':False,'executable':False}
    write_json(output/'frozen_m2_contract.json',contract)
    dataset=load_development(path)
    run='dev_A_base_v4'
    with sqlite3.connect((ROOT/'work/candidate_simulation.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        meta=json.loads(db.execute('SELECT metadata FROM candidate_runs WHERE run_id=?',(run,)).fetchone()[0])
        for name,expected in meta['source_hashes'].items():
            if file_hash(ROOT/'kquant_crypto'/name)!=expected:
                raise ValueError('Original source hash mismatch: '+name)
        if meta['data_manifest_hash']!=dataset.manifest['manifest_hash']:
            raise ValueError('Original data hash mismatch')
        rules=json.loads((ROOT/'outputs/dual_regime_v1/exchange_rules.json').read_text(encoding='utf-8'))['rules']
        if digest(rules)!=meta['rules_hash']:
            raise ValueError('Original rules hash mismatch')
        policy={**meta['config'],'data_manifest_hash':meta['data_manifest_hash']}
        features,opportunities,labels,delayed,records=collect(CandidatePortfolio(policy,rules),dataset)
        checks={}
        for kind,key in (('events','event_id'),('trades','trade_id'),('equity','time')):
            actual=[{**r,'run_id':run,**({'time':float(r['time'])} if kind=='equity' else {})} for r in records[kind]]
            saved=[json.loads(r[0]) for r in db.execute('SELECT payload FROM candidate_records WHERE run_id=? AND kind=?',(run,kind))]
            checks[kind]={'match':record_hash(actual,key)==record_hash(saved,key),'actual_hash':record_hash(actual,key),
                          'saved_hash':record_hash(saved,key),'count':len(actual)}
    write_json(output/'feature_schema.json',FEATURE_SCHEMA)
    write_json(output/'label_schema.json',LABEL_SCHEMA)
    write_json(output/'baseline_compatibility.json',checks)
    write_json(output/'partition_policy.json',split_policy)
    partitions=assign_partitions(labels,split_policy)
    for name,rows in [('features',features),('opportunities',opportunities),('labels',labels),('delayed_assessments',delayed),
                      ('quarantine',dataset.quarantine),('trades',records['trades']),('equity',records['equity']),
                      ('partitions',partitions)]:
        write_rows(output/(name+'.jsonl'),rows)
    write_json(output/'event_manifest.json',{'status':'NOT_COLLECTED','llm_enabled':False,'records':0,
                                         'reason':'M2 technical-only; no fabricated neutral event features'})
    sources=[Path(__file__),ROOT/'kquant_crypto/hybrid_dataset.py',ROOT/'kquant_crypto/hybrid_features.py',
             ROOT/'kquant_crypto/hybrid_labels.py',ROOT/'kquant_crypto/hybrid_label_contract.py',ROOT/'kquant_crypto/hybrid_partitions.py']
    status='PASS' if all(c['match'] for c in checks.values()) else 'BLOCKED_BASELINE_DIVERGENCE'
    report={'status':status,'scope':'M2 legacy descriptive dataset, not model admission',
            'built_at':datetime.now(timezone.utc).isoformat(),'elapsed_seconds':time.perf_counter()-started,
            'loaded_module_root':str(sys.modules['kquant_crypto'].__file__),
            'contract_hash':digest(contract),'data_manifest_hash':dataset.manifest['manifest_hash'],
            'authorized_cutoff':dataset.cutoff,'development_content_hash':dataset.content_hash,
            'source_hashes':{str(p.relative_to(ROOT)):file_hash(p) for p in sources},
            'artifacts':{p.name:file_hash(p) for p in sorted(output.iterdir()) if p.is_file()},
            'coverage':{s:{tf:len(rows) for tf,rows in series.items()} for s,series in dataset.bars.items()},
            'quarantine_count':len(dataset.quarantine),'feature_count':len(features),'opportunity_count':len(opportunities),
            'label_status_counts':dict(Counter(r['status'] for r in labels)),
            'mature_by_symbol_mode':dict(Counter(r['symbol']+':'+r['mode'] for r in labels if r['status']=='mature')),
            'delayed_status_counts':dict(Counter(r['reason'] for r in delayed)),
            'partition_eligible_counts':dict(Counter(r['partition'] for r in partitions if r['population_eligible'])),
            'partition_exclusion_counts':dict(Counter(r['exclusion_reason'] for r in partitions if not r['population_eligible'])),
            'exposure':'EXPOSED_DEVELOPMENT','strict_received_time_evidence':False,'performance_status':'PERFORMANCE_UNPROVEN',
            'model_training_enabled':False,'mathematical_filtering_enabled':False,'original_data_gate_modified':False}
    write_json(output/'report.json',report)
    print(json.dumps(report,ensure_ascii=False))
    return 0 if status=='PASS' else 2


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    raise SystemExit(build(args.output))
