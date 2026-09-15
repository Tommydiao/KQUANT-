"""Reproduce existing A/B development traces without writing their database."""

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import duckdb
from kquant_crypto.candidate_policy import digest
from kquant_crypto.candidate_simulation import CandidatePortfolio, replay
from kquant_crypto.strategy_dual_mode_v1 import Bar


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def trace_hash(rows, key):
    h=hashlib.sha256()
    for row in sorted(rows,key=lambda r:str(r[key])):
        h.update(json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
        h.update(b'\n')
    return h.hexdigest()


def verify(output):
    output=Path(output).resolve()
    allowed=(ROOT/'outputs/hybrid_regime_v1').resolve()
    if not output.is_relative_to(allowed) or output==allowed:
        raise ValueError('New isolated output directory required')
    output.mkdir(parents=True,exist_ok=False)
    frozen=ROOT/'outputs/dual_regime_v1/frozen'
    manifest=json.loads((frozen/'data_manifest.json').read_text(encoding='utf-8'))
    body={k:v for k,v in manifest.items() if k!='manifest_hash'}
    if digest(body)!=manifest['manifest_hash']:
        raise ValueError('Manifest mismatch')
    window=manifest['window']
    end=window['start']+int(window['days']*.7)*86400
    dataset={}
    row_limits={}
    with duckdb.connect(':memory:') as conn:
        for symbol in manifest['symbols']:
            dataset[symbol]={}
            for tf,duration in (('5m',300),('1h',3600)):
                entry=manifest['files'][symbol][tf]
                path=(frozen/entry['path']).resolve()
                if not path.is_relative_to(frozen.resolve()) or sha(path)!=entry['sha256']:
                    raise ValueError('Frozen file mismatch')
                rows=conn.execute('''SELECT start,open,high,low,close,volume FROM read_parquet(?)
                    WHERE start>=? AND start+?<=? ORDER BY start''',
                    [str(path),window['warmup_start'],duration,end]).fetchall()
                dataset[symbol][tf]=[Bar(*r) for r in rows]
                row_limits[symbol+':'+tf]={'rows':len(rows),'last_close':rows[-1][0]+duration}
    results={}
    db_uri=(ROOT/'work/candidate_simulation.sqlite3').as_uri()+'?mode=ro'
    with sqlite3.connect(db_uri,uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        for candidate in ('A','B'):
            run='dev_'+candidate+'_base_v4'
            meta_json,state_json=db.execute('SELECT metadata,state FROM candidate_runs WHERE run_id=?',(run,)).fetchone()
            meta,state=json.loads(meta_json),json.loads(state_json)
            for name,expected in meta['source_hashes'].items():
                if sha(ROOT/'kquant_crypto'/name)!=expected:
                    raise ValueError('Source mismatch: '+name)
            policy={**meta['config'],'data_manifest_hash':meta['data_manifest_hash']}
            rules=json.loads((ROOT/'outputs/dual_regime_v1/exchange_rules.json').read_text(encoding='utf-8'))['rules']
            if digest(rules)!=meta['rules_hash']:
                raise ValueError('Rules mismatch')
            portfolio=CandidatePortfolio(policy,rules)
            actual=replay(portfolio,dataset,start=window['start'],end=end)
            actual['equity']=[r for r in actual['equity'] if r['time']>=window['start']]
            checks={}
            for kind,key in (('events','event_id'),('trades','trade_id'),('equity','time')):
                # Reproduce only save()'s documented serialization envelope.
                # No price, decision, quantity, fee or risk value is normalized.
                actual[kind]=[{**r,'run_id':run,**({'time':float(r['time'])} if kind=='equity' else {})}
                              for r in actual[kind]]
                saved=[json.loads(r[0]) for r in db.execute('SELECT payload FROM candidate_records WHERE run_id=? AND kind=?',(run,kind))]
                checks[kind]={'count':len(actual[kind]),'saved_count':len(saved),
                              'actual_hash':trace_hash(actual[kind],key),'saved_hash':trace_hash(saved,key)}
                checks[kind]['match']=checks[kind]['actual_hash']==checks[kind]['saved_hash']
                actual_by_key={str(r[key]):r for r in actual[kind]}
                saved_by_key={str(r[key]):r for r in saved}
                differing=[k for k in actual_by_key.keys() | saved_by_key.keys()
                           if actual_by_key.get(k)!=saved_by_key.get(k)]
                checks[kind]['different_records']=len(differing)
                if differing:
                    k=sorted(differing)[0]
                    checks[kind]['first_difference']={'key':k,'actual':actual_by_key.get(k),'saved':saved_by_key.get(k)}
            results[run]=checks
            print(json.dumps({'run':run,'checks':checks}),flush=True)
    report={'development_end':end,'sealed_end':window['end'],'data_manifest_hash':manifest['manifest_hash'],
            'market_rows_after_development_end_read':False,'integrity_hashes_cover_complete_files':True,
            'row_limits':row_limits,'results':results,'baseline_cli_hash_missing_in_old_runs':True,
            'serialization_envelope':['run_id added by save','equity time cast to float by save'],
            'status':'PASS' if all(c['match'] for r in results.values() for c in r.values()) else 'FAIL',
            'scope':'existing A/B traces only, not a Hybrid plugin compatibility claim'}
    (output/'golden_trace_report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return 0 if report['status']=='PASS' else 2


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--output',required=True)
    args=p.parse_args()
    raise SystemExit(verify(args.output))
