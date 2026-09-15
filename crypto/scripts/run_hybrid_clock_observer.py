"""New independent observation clock segment, no changes to old logs/writers."""
import argparse
import asyncio
from collections import Counter
from dataclasses import asdict
from datetime import datetime,UTC
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import httpx
from websockets.asyncio.client import connect
from kquant_crypto.candidate_forward import REST_URL,WS_URL,SYMBOLS,bootstrap,_process_lock,_bar
from kquant_crypto.candidate_policy import load_policy
from kquant_crypto.hybrid_clock import POLICY,calibrate,native_ms,digest
from kquant_crypto.hybrid_observation import ObservationStore
from kquant_crypto.hybrid_public_observer import normalize_ticker


def save(path,value):
    path.write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False),encoding='utf-8')


async def probes(client):
    results=[]
    for i in range(POLICY['probes']):
        m0=time.perf_counter();l0=time.time()
        response=await client.get(REST_URL+'/api/v3/time',headers={'Cache-Control':'no-cache','Pragma':'no-cache'})
        l1=time.time();m1=time.perf_counter();response.raise_for_status()
        server=response.json()['serverTime'];converted=native_ms(server)
        results.append({'index':i,'serverTime':server,'server_time_utc':datetime.fromtimestamp(converted,UTC).isoformat(),
            'monotonic_before':m0,'monotonic_after':m1,'local_before':l0,'local_after':l1,
            'local_before_utc':datetime.fromtimestamp(l0,UTC).isoformat(),'local_after_utc':datetime.fromtimestamp(l1,UTC).isoformat(),
            'rtt':m1-m0,'server_minus_local_lower':converted-l1,'server_minus_local_upper':converted-l0,
            'age_seconds':float(response.headers.get('Age','0')),'response_headers':{k:response.headers.get(k) for k in ('date','age','cache-control','x-cache','content-type')},
            'response_sha256':hashlib.sha256(response.content).hexdigest(),'native_unit':'MILLISECOND',
            'request_time_unit_header':None,'endpoint':str(response.url)})
        await asyncio.sleep(.15)
    return results


async def run(out,seconds):
    # Freeze development clock policy and implementation before network observation.
    sources=['kquant_crypto/hybrid_clock.py','scripts/run_hybrid_clock_observer.py',
             'kquant_crypto/hybrid_observation.py','kquant_crypto/hybrid_public_observer.py']
    save(out/'preregistration.json',{'scope':'ONLINE_DATA_CONTRACT_ONLY','clock_policy':POLICY,
        'seconds':seconds,'source_hashes':{s:hashlib.sha256((ROOT/s).read_bytes()).hexdigest() for s in sources},
        'native_source_time_unchanged':True,'historical_quotes_rewritten':False,'model_loading':False,
        'execution_enabled':False,'created_at_local_utc':datetime.now(UTC).isoformat(),
        'clock_implementation':vars(time.get_clock_info('perf_counter'))})
    counters=Counter();qualified=[]; rejected=[];continuity=[];failure=None
    db_path=out/'hybrid_segment.sqlite3'
    rules=json.loads((ROOT/'outputs/dual_regime_v1/exchange_rules.json').read_text())['rules']
    store=ObservationStore(db_path,load_policy(candidate='A'),rules)
    def process(identity,event):
        result=store.process(identity,event)
        counters.update(r['reason'] for r in result.get('audit',[]) if 'reason' in r)
    segment=None
    try:
        async with httpx.AsyncClient(timeout=15,trust_env=False,follow_redirects=False) as client:
            clock_probes=await probes(client);save(out/'clock_probes.json',clock_probes)
            segment=calibrate(clock_probes);save(out/'clock_segment.json',asdict(segment)|{'segment_id':segment.segment_id})
            clock=segment.bounds(time.perf_counter(),time.time())
            # The lower bound guarantees that historical bootstrap bars are closed.
            five,hourly=await bootstrap(client,SYMBOLS,clock['received_at_lower'])
        clock=segment.bounds(time.perf_counter(),time.time())
        process('warmup',{'type':'warmup',**clock,'five':{s:[asdict(b) for b in rows] for s,rows in five.items()},
            'hourly':{s:{str(t):asdict(b) for t,b in rows.items()} for s,rows in hourly.items()},
            'availability_basis':'fetched_now_warmup_only','source':REST_URL})
        streams='/'.join(s.lower()+suffix for s in SYMBOLS for suffix in ('@ticker','@kline_5m'))
        pending={};started=time.perf_counter();last_seen={}
        with _process_lock(out/'segment.lock'):
            async with connect(WS_URL+'?streams='+streams,open_timeout=15,ping_interval=20,ping_timeout=20,max_queue=16) as ws:
                while time.perf_counter()-started<seconds:
                    try:raw=await asyncio.wait_for(ws.recv(),timeout=min(2,seconds-(time.perf_counter()-started)))
                    except asyncio.TimeoutError:
                        clock=segment.bounds(time.perf_counter(),time.time())
                        process('clock:'+digest(clock),{'type':'clock',**clock});continue
                    clock=segment.bounds(time.perf_counter(),time.time())
                    message=json.loads(raw);data=message.get('data',{})
                    if message.get('stream','').endswith('@ticker'):
                        event=normalize_ticker(message,clock['received_at_upper'])|clock
                        native=native_ms(data['E'])
                        if native!=event['source_time']:raise ValueError('Source event time changed')
                        event['source_event_time_native_ms']=data['E']
                        event['receiver_clock_policy_id']=POLICY['version']
                        event['clock_validation']=segment.check_quote(native,clock)
                        symbol=event['symbol']
                        if symbol in last_seen and native-last_seen[symbol]>30:
                            continuity.append({'symbol':symbol,'gap':native-last_seen[symbol],'source_time':native})
                            process('gap:'+digest(event),{'type':'disconnect',**clock,'reason':'native_quote_gap'})
                        last_seen[symbol]=native
                        if event['clock_validation']=='qualified_time_interval':
                            process('quote:'+symbol+':'+str(data['E']),event);qualified.append(event)
                        else:
                            rejected.append(event);counters[event['clock_validation']]+=1
                    elif data.get('k',{}).get('x') is True:
                        k=data['k'];symbol=data.get('s')
                        if symbol not in SYMBOLS or k.get('i')!='5m':continue
                        b=_bar(k['t'],[k[x] for x in ('o','h','l','c','v')],300)
                        if k['T']!=(b.start+300)*1000-1:raise ValueError('Invalid bar boundary units')
                        if b.start+300>clock['received_at_lower']:
                            counters['closed_bar_receipt_order_uncertain']+=1;continue
                        bucket=pending.setdefault(b.start,{})
                        bucket[symbol]=asdict(b)
                        if len(bucket)==3:
                            process('closed:'+str(b.start),{'type':'closed_batch',**clock,'five':bucket,
                                'requires_commit_observation':True,'source':'binance_closed_5m'})
                            committed=segment.bounds(time.perf_counter(),time.time())
                            process('commit:'+str(b.start),{'type':'commit_observed',**committed,'signal_time':b.start+300})
                            pending={t:rows for t,rows in pending.items() if t>b.start}
                        if len(pending)>2:raise ValueError('Missing common closed bar')
    except Exception as exc:
        failure={'type':type(exc).__name__,'detail':str(exc) if isinstance(exc,ValueError) else 'See source state; no relaxation applied'}
    finally:
        if segment:
            try:
                clock=segment.bounds(time.perf_counter(),time.time())
                process('end',{'type':'observation_end',**clock,'reason':'bounded_segment_ended'})
            except Exception as exc:
                failure=failure or {'type':type(exc).__name__,'detail':'Clock/persistence unavailable at segment close'}
        for name,rows in [('qualified_quotes.jsonl',qualified),('rejected_quotes.jsonl',rejected)]:
            with (out/name).open('w',encoding='utf-8') as f:
                for row in rows:f.write(json.dumps(row,sort_keys=True,allow_nan=False)+'\n')
        checkpoint=store.db.execute('SELECT state FROM observer_checkpoint WHERE id=1').fetchone()
        items=json.loads(checkpoint[0])['opportunities'] if checkpoint else {}
        report={'failure':failure,'clock_segment_id':segment.segment_id if segment else None,
            'time_qualified_quotes':len(qualified),'eligible_quotes':counters['valid_quote_consumed'],
            'rejected_quotes':len(rejected),'reasons':dict(counters),
            'continuity_gaps':continuity,'opportunities':len(items),
            'fill_statuses':dict(Counter(x['fill_status'] for x in items.values())),
            'label_statuses':dict(Counter(x['label_status'] for x in items.values())),
            'system_clock_modified':False,'old_writer_modified':False,'source_event_time_modified':False,
            'math_filtering_enabled':False,'scope':'NEW_RECEIVER_CLOCK_RESEARCH_SEGMENT',
            'old_conflicting_records_repaired':False,'sampling':'ticker_1000ms_not_full_tick_tape',
            'python':sys.executable,'observer_contract_hash':store.contract}
        store.close();save(out/'report.json',report);print(json.dumps(report,indent=2))
    return 1 if failure else 0


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);parser.add_argument('--seconds',type=float,default=90)
    args=parser.parse_args()
    if not 1<=args.seconds<=300:raise ValueError('Bounded clock observation 1..300 seconds')
    out=(ROOT/args.output).resolve()
    if not out.is_relative_to(ROOT/'outputs/hybrid_regime_v1'):raise ValueError('Independent new Hybrid output only')
    out.mkdir(parents=True,exist_ok=False)
    return asyncio.run(run(out,args.seconds))


if __name__=='__main__':sys.exit(main())
