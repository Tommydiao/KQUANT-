"""Bounded public-only acquisition for Hybrid, never owns the original writer.

The 24hr ticker carries exchange E plus b/B/a/A. Its 1-second samples are not a
complete order-book tape; E is an ordering clock, not an order-book sequence ID.
"""
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import time

import httpx
from websockets.asyncio.client import connect

from .candidate_forward import WS_URL, SYMBOLS, bootstrap, _process_lock, _bar
from .candidate_policy import digest


def normalize_ticker(message, received_at):
    raw=message.get('data',{})
    symbol=raw.get('s')
    if symbol not in SYMBOLS or message.get('stream')!=symbol.lower()+'@ticker' or raw.get('e')!='24hrTicker':
        raise ValueError('Expected Binance spot ticker envelope')
    if type(raw.get('E')) is not int:
        raise ValueError('Exchange event time required')
    return {'type':'quote','symbol':symbol,'source_time':raw['E']/1000,'received_at':received_at,
            'source_time_basis':'exchange_event_time','sequence':raw['E'],
            'sequence_basis':'exchange_event_time_not_book_update_sequence',
            'bid':float(raw['b']),'ask':float(raw['a']), 'bid_size':float(raw['B']),'ask_size':float(raw['A']),
            'venue':'binance','market_type':'spot','provider_status':'live',
            'source':WS_URL,'stream':message['stream'],'raw_payload_hash':digest(raw),
            'sampling':'1000ms_ticker_snapshot_not_complete_order_book_tape'}


async def audit_clock():
    from .candidate_forward import REST_URL
    results=[]
    async with httpx.AsyncClient(timeout=15,trust_env=False,follow_redirects=False) as client:
        for _ in range(3):
            begin=time.time(); response=await client.get(REST_URL+'/api/v3/time'); end=time.time()
            response.raise_for_status(); server=response.json()['serverTime']/1000
            results.append({'local_before':begin,'local_after':end,'server_time':server,
                'round_trip_seconds':end-begin,'offset_lower_bound':server-end,'offset_upper_bound':server-begin})
    return {'source':REST_URL+'/api/v3/time','samples':results,'diagnostic_only':True,
            'system_clock_changed':False,'timestamp_corrections_applied':False}


async def observe(store, *, seconds, lock_path):
    if not 0 < seconds <= 3600:
        raise ValueError('Bounded forward observation: 1..3600 seconds')
    records=[]
    with _process_lock(Path(lock_path)):
        saved=store.db.execute('SELECT state FROM observer_checkpoint WHERE id=1').fetchone()
        state=json.loads(saved[0]) if saved else {}
        if not state.get('watermarks',{}).get('bar'):
            async with httpx.AsyncClient(timeout=15,trust_env=False,follow_redirects=False) as client:
                five,hourly=await bootstrap(client,SYMBOLS,time.time())
            event={'type':'warmup','received_at':time.time(),
                'five':{s:[asdict(b) for b in bars] for s,bars in five.items()},
                'hourly':{s:{str(t):asdict(b) for t,b in bars.items()} for s,bars in hourly.items()},
                'source':'binance_public_closed_history','availability_basis':'fetched_now_for_warmup_only'}
            store.process('warmup:'+digest(event),event)
        else:
            event={'type':'disconnect','received_at':time.time(),'reason':'resumed_observation_unobserved_interval'}
            store.process('resume:'+digest(event),event)
        streams='/'.join(s.lower()+suffix for s in SYMBOLS for suffix in ('@ticker','@kline_5m'))
        pending={}
        started=time.monotonic()
        try:
            async with connect(WS_URL+'?streams='+streams,open_timeout=15,ping_interval=20,ping_timeout=20,max_queue=16) as ws:
                while time.monotonic()-started < seconds:
                    try:
                        raw=await asyncio.wait_for(ws.recv(),timeout=min(2,seconds-(time.monotonic()-started)))
                    except asyncio.TimeoutError:
                        event={'type':'clock','received_at':time.time()}
                        store.process('clock:'+digest(event),event)
                        continue
                    receipt=time.time(); message=json.loads(raw); data=message.get('data',{})
                    if message.get('stream','').endswith('@ticker'):
                        event=normalize_ticker(message,receipt)
                        result=store.process('ticker:'+event['symbol']+':'+str(data['E'])+':'+digest(data),event)
                        records.extend(result.get('audit',[]))
                    elif data.get('k',{}).get('x') is True:
                        k=data['k'];symbol=data.get('s')
                        if symbol not in SYMBOLS or k.get('i')!='5m':continue
                        b=_bar(k['t'],[k[x] for x in ('o','h','l','c','v')],300)
                        if k.get('T')!=(b.start+300)*1000-1 or receipt<b.start+300:
                            raise ValueError('Unclosed public bar')
                        part=pending.setdefault(b.start,{})
                        part[symbol]=asdict(b)
                        if len(part)==3:
                            event={'type':'closed_batch','received_at':receipt,'five':part,
                                   'source':'binance_public_closed_5m','available_at':receipt,
                                   'requires_commit_observation':True}
                            store.process('closed:'+str(b.start),event)
                            committed={'type':'commit_observed','signal_time':b.start+300,'received_at':time.time()}
                            store.process('committed:'+str(b.start),committed)
                            pending={t:p for t,p in pending.items() if t>b.start}
                    # A bounded buffer cannot silently bridge absent closed bars.
                    if len(pending)>2:
                        raise ValueError('Unresolved common closed-bar gap')
        finally:
            event={'type':'observation_end','received_at':time.time(),'reason':'bounded_observation_ended'}
            store.process('end:'+digest(event),event)
    return records
