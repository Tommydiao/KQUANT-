"""Bounded independent public receiver; no bootstrap, model loading or orders."""
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
from kquant_crypto.hybrid_hourly_receipt import normalize_hourly, SYMBOLS, VERSION
from kquant_crypto.hybrid_factor_journal import FactorJournal

WS = 'wss://data-stream.binance.vision/stream'


def commit_receipt(journal, record, event, sequence, receipt):
    """Persist the freeze evidence before either recoverable journal write."""
    frozen = math.ceil(receipt['received_at_upper'])
    intent = dict(kind='freeze_intent', sequence=sequence,
                  event_id=event['event_id'], event_hash=digest(event),
                  frozen_at=frozen, receipt=receipt)
    record(intent)
    applied = journal.append(event['event_id'], event['payload'])
    snapshots = journal.advance('freeze:'+str(sequence), frozen)
    record(dict(kind='journal_commit', sequence=sequence, event_id=event['event_id'],
                result=applied, snapshot_count=len(snapshots), frozen_at=frozen))
    return snapshots


async def observe(out, seconds):
    out.mkdir(parents=True, exist_ok=False)
    counts = Counter()
    journal = None
    failure = None
    started = time.perf_counter()
    manifest = dict(scope='DEV_ONLY', duration_seconds=seconds, symbols=sorted(SYMBOLS),
        interval='1h', receipt_basis='OBSERVED_RECEIPT', adapter_version=VERSION,
        bootstrap=False, execution_enabled=False, model_loading=False,
        started_local_utc=time.time(), interpreter=sys.executable,
        continuity='One connection only; failures terminate this segment, no backfill',
        max_messages=2000)
    sources = [Path(__file__), ROOT/'kquant_crypto/hybrid_hourly_receipt.py',
               ROOT/'kquant_crypto/hybrid_clock.py', ROOT/'kquant_crypto/hybrid_probe_recording.py',
               ROOT/'kquant_crypto/hybrid_factor_journal.py']
    manifest['source_hashes'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    with (out/'receipts.jsonl').open('x', encoding='utf-8') as log:
        def record(value):
            log.write(json.dumps(value, sort_keys=True, allow_nan=False)+'\n')
            log.flush()
            os.fsync(log.fileno())
        try:
            async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
                segment = calibrate(await probes(client, record))
            record(dict(kind='clock_segment', segment=asdict(segment), segment_id=segment.segment_id))
            receipt = segment.bounds(time.perf_counter(), time.time())
            first_close = (math.floor(receipt['received_at_upper']/3600)+1)*3600
            record(dict(kind='journal_contract', first_close=first_close,
                        receipt_basis='OBSERVED_RECEIPT',
                        source='binance_spot_native_utc_kline_1h'))
            journal = FactorJournal(out/'factors.sqlite3', first_close=first_close,
                receipt_basis='OBSERVED_RECEIPT', source='binance_spot_native_utc_kline_1h')
            streams = '/'.join(s.lower()+'@kline_1h' for s in sorted(SYMBOLS))
            deadline = time.perf_counter()+seconds
            async with connect(WS+'?streams='+streams, open_timeout=10, max_size=65536,
                               max_queue=32, ping_interval=20, ping_timeout=10) as ws:
                while time.perf_counter() < deadline and counts['messages'] < 2000:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=max(.001, deadline-time.perf_counter()))
                    except asyncio.TimeoutError:
                        break
                    mono, local = time.perf_counter(), time.time()
                    counts['messages'] += 1
                    # Durable raw receipt precedes parsing and every factor write.
                    record(dict(kind='raw_message', sequence=counts['messages'], raw=raw,
                                received_at_monotonic=mono, received_at_local_utc=local,
                                clock_segment_id=segment.segment_id))
                    try:
                        message = json.loads(raw)
                        result = normalize_hourly(message, segment, monotonic_at=mono, local_at=local)
                    except (ValueError, TypeError, AttributeError) as exc:
                        result = dict(accepted=False, reason='malformed_message', error_type=type(exc).__name__)
                    record(dict(kind='normalization', sequence=counts['messages'], result=result))
                    if not result['accepted']:
                        counts['rejected'] += 1
                        counts['reason:'+result['reason']] += 1
                        continue
                    event = result['event']
                    snapshots = commit_receipt(journal, record, event, counts['messages'],
                        segment.bounds(time.perf_counter(), time.time()))
                    counts['accepted_messages'] += 1
                    counts['snapshots'] += len(snapshots)
        except Exception as exc:
            failure = dict(error_type=type(exc).__name__, detail=str(exc)[:500])
            record(dict(kind='terminal_failure', failure=failure))
        finally:
            if journal is not None:
                journal.close()
    report = dict(status='FAILED' if failure else 'BOUNDED_OBSERVATION_COMPLETE',
        counts=dict(counts), failure=failure, elapsed_seconds=time.perf_counter()-started,
        execution_enabled=False, model_loading=False, quote_labels=0,
        live_acceptance=False, warmup_complete=False,
        receipts_sha256=hashlib.sha256((out/'receipts.jsonl').read_bytes()).hexdigest(),
        manifest_hash=digest(manifest))
    (out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--seconds', type=int, default=30)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 300:
        raise ValueError('One clock segment supports only bounded 1..300 second runs')
    result = asyncio.run(observe(Path(args.output).resolve(), args.seconds))
    print(json.dumps(result))
    sys.exit(1 if result['failure'] else 0)
