"""Read-only, development-window-only input for Hybrid M2."""

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

import duckdb

from .candidate_policy import digest
from .strategy_dual_mode_v1 import Bar

SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')


def file_hash(path):
    result=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            result.update(block)
    return result.hexdigest()


@dataclass
class Dataset:
    bars: dict
    provenance: dict
    manifest: dict
    quarantine: list
    cutoff: int
    content_hash: str


def clean_rows(rows, duration, cutoff):
    grouped={}
    quarantine=[]
    for row in rows:
        stamp=row.get('start')
        try:
            bar=Bar(**{k:row[k] for k in ('start','open','high','low','close','volume')})
            if stamp % duration or stamp+duration>cutoff:
                raise ValueError('forming_or_misaligned')
            if row['available_at']!=stamp+duration or row['availability_basis']!='assumed_close_historical_replay':
                raise ValueError('unsupported_availability_basis')
            if row['provider_status']!='historical':
                raise ValueError('unsupported_source_status')
        except (ValueError,KeyError,TypeError) as exc:
            quarantine.append({'start':stamp,'reason':str(exc)})
            # A malformed duplicate invalidates the whole timestamp.
            grouped.setdefault(stamp,[]).append(None)
            continue
        grouped.setdefault(stamp,[]).append((bar,row))
    bars=[]
    provenance={}
    for stamp,values in sorted(grouped.items(),key=lambda item:str(item[0])):
        valid=[v for v in values if v is not None]
        if len(valid)!=len(values) or any(v[0]!=valid[0][0] for v in valid[1:]):
            quarantine.append({'start':stamp,'reason':'invalid_or_conflicting_duplicate'})
            continue
        bar,row=valid[0]
        bars.append(bar)
        provenance[stamp]={k:row[k] for k in ('available_at','availability_basis','received_at','provider_status')}
        provenance[stamp]['receipt_variants']=sorted({str(v[1]['received_at']) for v in valid})
        if len(valid)>1:
            quarantine.append({'start':stamp,'reason':'exact_duplicate_collapsed','count':len(valid)})
    return sorted(bars,key=lambda b:b.start),provenance,quarantine


def proven_hours(fives, hours):
    by_start={b.start:b for b in fives}
    accepted=[]
    rejected=[]
    for h in hours:
        children=[by_start.get(h.start+i*300) for i in range(12)]
        if any(b is None for b in children):
            rejected.append({'start':h.start,'reason':'missing_5m_child'})
            continue
        expected=(children[0].open,max(b.high for b in children),min(b.low for b in children),
                  children[-1].close,math.fsum(b.volume for b in children))
        actual=(h.open,h.high,h.low,h.close,h.volume)
        if not all(math.isclose(a,b,rel_tol=1e-8,abs_tol=1e-8) for a,b in zip(expected,actual)):
            rejected.append({'start':h.start,'reason':'hour_ohlcv_mismatch'})
            continue
        accepted.append(h)
    return accepted,rejected


def load_development(manifest_path, *, cutoff=None):
    manifest_path=Path(manifest_path).resolve()
    root=manifest_path.parent
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    if digest({k:v for k,v in manifest.items() if k!='manifest_hash'})!=manifest['manifest_hash']:
        raise ValueError('Manifest hash mismatch')
    if manifest.get('schema_version')!=1 or tuple(manifest['symbols'])!=SYMBOLS:
        raise ValueError('Only frozen BTC/ETH/SOL Spot schema is supported')
    if manifest.get('source')!='binance:spot:market_specific_compacted_closed_klines':
        raise ValueError('Unapproved source/market')
    window=manifest['window']
    end=window['start']+int(window['days']*.7)*86400
    cutoff=end if cutoff is None else cutoff
    if type(cutoff) is not int or cutoff%300 or not window['start']<cutoff<=end:
        raise ValueError('Only authorized development cutoff is allowed')
    bars={}; provenance={}; quarantine=[]
    with duckdb.connect(':memory:') as db:
        for symbol in SYMBOLS:
            bars[symbol]={}; provenance[symbol]={}
            for tf,duration in (('5m',300),('1h',3600)):
                entry=manifest['files'][symbol][tf]
                path=(root/entry['path']).resolve()
                if not path.is_relative_to(root) or file_hash(path)!=entry['sha256']:
                    raise ValueError('Frozen file path/hash mismatch')
                cursor=db.execute('''SELECT start,open,high,low,close,volume,available_at,
                    availability_basis,received_at,provider_status FROM read_parquet(?)
                    WHERE start>=? AND start+?<=? ORDER BY start''',
                    [str(path),window['warmup_start'],duration,cutoff])
                names=[d[0] for d in cursor.description]
                rows=[dict(zip(names,r)) for r in cursor.fetchall()]
                clean,source,invalid=clean_rows(rows,duration,cutoff)
                bars[symbol][tf]=clean; provenance[symbol][tf]=source
                quarantine.extend(dict(r,symbol=symbol,timeframe=tf) for r in invalid)
            hours,invalid=proven_hours(bars[symbol]['5m'],bars[symbol]['1h'])
            bars[symbol]['1h']=hours
            quarantine.extend(dict(r,symbol=symbol,timeframe='1h') for r in invalid)
    content=digest({s:{tf:[vars(b) for b in rows] for tf,rows in series.items()} for s,series in bars.items()})
    return Dataset(bars,provenance,manifest,quarantine,cutoff,content)
