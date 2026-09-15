"""Bounded, exposed-development loader for MC input engineering only."""
from __future__ import annotations
import json
from pathlib import Path

from .hybrid_delivery import sha
from .hybrid_mc_paths_v12 import SYMBOLS, DevPathSpec, audit_history
from .candidate_policy import digest

AUTHORIZED_START=1754006400
AUTHORIZED_END=1776038400
MANIFEST_HASH='42b913eca5de81541e89499e2afa846757b724ef4fbe0f365a80d52397a5651a'


def bounded_rows(path,start,end):
    """Predicate runs inside DuckDB before rows are materialized into Python."""
    import duckdb
    con=duckdb.connect(':memory:',config={'threads':'1','memory_limit':'256MB'})
    try:
        cursor=con.execute('''SELECT start,open,high,low,close,volume,available_at,availability_basis
            FROM read_parquet(?) WHERE start >= ? AND start < ? AND available_at <= ? ORDER BY start''',
            [str(path),start,end,end])
        names=[d[0] for d in cursor.description]
        return [dict(zip(names,r)) for r in cursor.fetchall()]
    finally:con.close()


def load_authorized(root, *, start, end):
    if type(start) is not int or type(end) is not int or start%300 or end%300:
        raise ValueError('Aligned explicit window required')
    if not AUTHORIZED_START<=start<end<=AUTHORIZED_END:
        raise ValueError('Outside authorized development interval; no market read performed')
    if end-start>32*86400:raise ValueError('Bounded engineering input budget exceeded')
    root=Path(root).resolve(); frozen=root/'outputs/dual_regime_v1/frozen'
    manifest=frozen/'data_manifest.json'
    m=json.loads(manifest.read_text())
    if m.get('manifest_hash')!=MANIFEST_HASH or digest({k:v for k,v in m.items() if k!='manifest_hash'})!=MANIFEST_HASH:
        raise ValueError('Frozen manifest canonical content changed')
    tables={};inputs={};queries=[]
    for symbol in SYMBOLS:
        entry=m['files'][symbol]['5m'];path=(frozen/entry['path']).resolve()
        if not path.is_relative_to(frozen) or sha(path)!=entry['sha256']:
            raise ValueError('Frozen source mismatch')
        rows=bounded_rows(path,start,end)
        if len(rows)!=(end-start)//300:raise ValueError('Window gap/duplicate; no drop and stitch')
        tables[symbol]=rows;inputs[str(path.relative_to(root))]=entry['sha256']
        queries.append({'symbol':symbol,'start_gte':start,'start_lt':end,'available_lte':end,
                        'returned_rows':len(rows),'predicate_before_materialization':True})
    history=[]
    for i,t in enumerate(range(start,end,300)):
        bars={}
        for s in SYMBOLS:
            row=tables[s][i]
            if row['start']!=t or row['available_at']!=t+300 or row['availability_basis']!='assumed_close_historical_replay':
                raise ValueError('Continuity or availability contract mismatch')
            bars[s]={**row,'source_bar_id':f'binance:spot:{s}:5m:{t}'}
        history.append({'start':t,'bars':bars})
    spec=DevPathSpec(start,end,end,12,72,32,20260906,len(history),32*72*3,MANIFEST_HASH,'EXPOSED_DEV_AUTHORIZED')
    audit=audit_history(history,spec)
    return history,spec,{'queries':queries,'source_hashes':inputs,'audit':audit,
                         'manifest_file_sha256':sha(manifest),'manifest_canonical_content_hash':MANIFEST_HASH,
                         'historical_received_at_not_simulated':True,'exposure':'EXPOSED_RESEARCH',
                         'market_rows_outside_authorized_window_materialized':False}
