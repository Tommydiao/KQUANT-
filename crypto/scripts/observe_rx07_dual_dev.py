"""Independent bounded receive-only run with asynchronous clock renewal."""
import argparse
import asyncio
from collections import Counter
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from websockets.asyncio.client import connect
from kquant_crypto.hybrid_clock import calibrate, digest
from kquant_crypto.hybrid_probe_recording import probes
from kquant_crypto.hybrid_dual_receipt import normalize_closed, renewal_overlap, INTERVALS
from kquant_crypto.hybrid_hourly_receipt import SYMBOLS

WS = 'wss://data-stream.binance.vision/stream'


class ClosedLedger:
    def __init__(self, receipt_upper):
        self.expected = {(s, i): (math.floor(receipt_upper/d)+1)*d
                         for s in SYMBOLS for i, d in INTERVALS.items()}
        self.seen = {}
        self.batches = {}

    def accept(self, row):
        key = (row['symbol'], row['interval'])
        identity = row['event_id']
        content = digest(row['bar'])
        if identity in self.seen:
            if self.seen[identity] != content:
                raise ValueError('conflicting_closed_bar')
            return 'duplicate'
        close = row['close_time']
        if close != self.expected[key]:
            raise ValueError('closed_bar_gap_or_out_of_order')
        self.seen[identity] = content
        self.expected[key] += INTERVALS[key[1]]
        batch = self.batches.setdefault((key[1], close), set())
        batch.add(key[0])
        return 'synchronized_batch' if batch == SYMBOLS else 'new_closed_bar'


async def observe(out, seconds):
    if not 1 <= seconds <= 259200:
        raise ValueError('Run duration must be 1..259200 seconds')
    out.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    counts, failure, renewal = Counter(), None, None
    connection_start = None
    receive_finished = None
    sources = [Path(__file__), ROOT/'kquant_crypto/hybrid_dual_receipt.py',
               ROOT/'kquant_crypto/hybrid_hourly_receipt.py', ROOT/'kquant_crypto/hybrid_clock.py',
               ROOT/'kquant_crypto/hybrid_probe_recording.py']
    manifest = dict(scope='DEV_ONLY_RECEIPT', seconds=seconds, pid=os.getpid(),
        interpreter=sys.executable, started_local_utc=time.time(), symbols=sorted(SYMBOLS),
        intervals=list(INTERVALS), renewal_seconds=240, max_messages=seconds*10+100,
        continuity='Single connection; failure ends run; no reconnect or backfill',
        execution_enabled=False, model_loading=False, bootstrap=False,
        source_hashes={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    with (out/'receipts.jsonl').open('x', encoding='utf-8') as log:
        def record(row):
            log.write(json.dumps(row, sort_keys=True, allow_nan=False)+'\n')
            log.flush()
            os.fsync(log.fileno())
        async def calibration(client):
            return calibrate(await probes(client, record))
        try:
            async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
                segment = await calibration(client)
                record(dict(kind='clock_segment', segment=asdict(segment), segment_id=segment.segment_id))
                streams = '/'.join(s.lower()+'@kline_'+i for s in sorted(SYMBOLS) for i in INTERVALS)
                async with connect(WS+'?streams='+streams, open_timeout=10, max_size=65536,
                                   max_queue=32, ping_interval=20, ping_timeout=10) as ws:
                    connection_start = time.perf_counter()
                    deadline = connection_start+seconds
                    ledger = ClosedLedger(segment.bounds(connection_start, time.time())['received_at_upper'])
                    record(dict(kind='connection_open', monotonic_at=connection_start,
                                expected_first_closes={s+':'+i: v for (s,i),v in ledger.expected.items()}))
                    heartbeat = connection_start
                    while time.perf_counter() < deadline:
                        mono, local = time.perf_counter(), time.time()
                        segment.bounds(mono, local)
                        if renewal is not None and renewal.done():
                            new = renewal.result()
                            if not renewal_overlap(segment, new, monotonic_at=mono, local_at=local):
                                raise ValueError('clock_renewal_disjoint')
                            record(dict(kind='clock_renewal', previous_segment_id=segment.segment_id,
                                        segment=asdict(new), segment_id=new.segment_id, overlap=True))
                            segment, renewal = new, None
                            counts['clock_renewals'] += 1
                        if renewal is None and mono-segment.mono_anchor >= 240:
                            renewal = asyncio.create_task(calibration(client))
                        if (out/'STOP').exists():
                            raise ValueError('operator_stop_incomplete_segment')
                        if mono-heartbeat >= 15:
                            record(dict(kind='heartbeat', elapsed_connected=mono-connection_start, counts=dict(counts)))
                            heartbeat = mono
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=min(1, max(.001, deadline-mono)))
                        except asyncio.TimeoutError:
                            continue
                        mono, local = time.perf_counter(), time.time()
                        counts['messages'] += 1
                        if isinstance(raw, bytes):
                            raw = raw.decode('utf-8')
                        record(dict(kind='raw_message', sequence=counts['messages'], raw=raw,
                                    received_at_monotonic=mono, received_at_local_utc=local,
                                    clock_segment_id=segment.segment_id))
                        try:
                            row = normalize_closed(json.loads(raw), segment, monotonic_at=mono, local_at=local)
                        except (ValueError, TypeError):
                            row = dict(accepted=False, reason='malformed_message')
                        record(dict(kind='normalization', sequence=counts['messages'], result=row))
                        if row['accepted']:
                            state = ledger.accept(row)
                            counts[state+':'+row['interval']] += 1
                            record(dict(kind='closed_ledger', event_id=row['event_id'], state=state))
                        else:
                            counts['reason:'+row['reason']] += 1
                            if row['reason'] != 'forming_bar':
                                raise ValueError('receipt_contract_rejected:'+row['reason'])
                        if counts['messages'] >= manifest['max_messages']:
                            raise ValueError('message_limit')
                    receive_finished = time.perf_counter()
                    record(dict(kind='receive_window_complete', monotonic_at=receive_finished,
                                receive_seconds=receive_finished-connection_start))
                    # Missing final closed messages cannot be hidden by timeout success.
                    lower = segment.bounds(time.perf_counter(), time.time())['received_at_lower']
                    overdue = {s+':'+i: v for (s,i),v in ledger.expected.items() if v+30 < lower}
                    if overdue:
                        record(dict(kind='overdue_boundaries', overdue=overdue))
                        raise ValueError('missing_closed_boundary')
        except Exception as exc:
            failure = dict(type=type(exc).__name__, detail=str(exc)[:500])
            record(dict(kind='terminal_failure', failure=failure))
        finally:
            if renewal is not None:
                renewal.cancel()
                await asyncio.gather(renewal, return_exceptions=True)
    report = dict(status='FAILED' if failure else 'RECEIPT_SEGMENT_COMPLETE', failure=failure,
        elapsed_seconds=time.perf_counter()-started, counts=dict(counts), manifest_hash=digest(manifest),
        receive_seconds=None if receive_finished is None else receive_finished-connection_start,
        receive_window_completed=receive_finished is not None,
        warmup_complete=False, signal_ready=False, execution_ready=False, model_loading=False,
        quote_labels=0, receipt_only=True)
    (out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--seconds', type=int, default=7200)
    args = parser.parse_args()
    result = asyncio.run(observe(Path(args.output).resolve(), args.seconds))
    print(json.dumps(result), flush=True)
    sys.exit(1 if result['failure'] else 0)
