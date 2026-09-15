"""Outcome-blind fixed RX05 matching. Not an entry filter."""
import hashlib
import json
import math


def select_reference(signal, rows, excluded):
    time=signal['as_of'];vol=signal['atr_fraction']
    if not math.isfinite(vol) or vol<=0:raise ValueError('Positive signal volatility required')
    candidates=[];seen=set()
    for row in rows:
        key=(row['symbol'],row['as_of'])
        if key in seen:raise ValueError('Duplicate reference snapshot')
        seen.add(key)
        if (row['symbol']!=signal['symbol'] or row['mode']!=signal['mode'] or
            not time-604800<=row['as_of']<time or row['as_of']%3600!=time%3600 or
            key in excluded or row['available_at']>row['as_of']):continue
        value=row['atr_fraction']
        if not math.isfinite(value) or value<=0 or not .8<=value/vol<=1.25:continue
        payload=json.dumps([20260909,signal['economic_signal_id'],row['as_of']],separators=(',',':'))
        candidates.append((hashlib.sha256(payload.encode()).hexdigest(),row))
    if not candidates:return dict(status='UNMATCHED',eligible_candidates=0,reference=None)
    digest,row=min(candidates,key=lambda item:item[0])
    return dict(status='MATCHED',eligible_candidates=len(candidates),reference=dict(row),selection_hash=digest)
