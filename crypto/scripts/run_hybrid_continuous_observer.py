"""Bounded long public research observation. No order or model consumers."""
import argparse
import asyncio
from collections import Counter
from dataclasses import asdict
from datetime import datetime, UTC
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
from websockets.asyncio.client import connect
from kquant_crypto.hybrid_probe_recording import probes
from kquant_crypto.candidate_forward import REST_URL, WS_URL, SYMBOLS, bootstrap, _process_lock, _bar
from kquant_crypto.candidate_policy import load_policy
from kquant_crypto.hybrid_clock import POLICY, calibrate, digest, native_ms
from kquant_crypto.hybrid_continuous_clock import renewal_due, validate_renewal
from kquant_crypto.hybrid_closed_batch_queue import ClosedBatchQueue
from kquant_crypto.hybrid_delivery import atomic_json, sha
from kquant_crypto.hybrid_observation import ObservationStore
from kquant_crypto.hybrid_public_observer import normalize_ticker
from kquant_crypto.hybrid_observation_window import planned_window, registration_wait, connection_failure_detail
from kquant_crypto.hybrid_observer_status_io import publish_status, io_failure_detail
from kquant_crypto.hybrid_failure_frames import failure_frames
from kquant_crypto.hybrid_observer_cleanup import cancel_renewal, capture_before_cleanup


async def observe(out, seconds):
    sources = ['scripts/run_hybrid_continuous_observer.py', 'kquant_crypto/hybrid_probe_recording.py',
               'kquant_crypto/hybrid_failure_frames.py',
               'kquant_crypto/hybrid_observer_cleanup.py',
               'kquant_crypto/hybrid_observer_status_io.py',
               'kquant_crypto/hybrid_observation_window.py',
               'kquant_crypto/hybrid_clock.py', 'kquant_crypto/hybrid_continuous_clock.py',
               'kquant_crypto/hybrid_closed_batch_queue.py',
               'kquant_crypto/hybrid_observation.py', 'kquant_crypto/hybrid_public_observer.py',
               'kquant_crypto/candidate_policy.py', 'kquant_crypto/candidate_simulation.py',
               'kquant_crypto/strategy_dual_mode_v1.py', 'kquant_crypto/candidate_forward.py']
    hashes = {s: sha(ROOT / s) for s in sources}
    for source in sources:
        target = out / 'sources' / source
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / source, target)
        if sha(target) != hashes[source]:
            raise ValueError('Source changed during preregistration')
    window = planned_window(time.perf_counter(), seconds)
    started = window['start_monotonic']
    atomic_json(out / 'preregistration.json', {
        'scope': 'CONTINUOUS_RECEIVER_INTERVAL_RESEARCH', 'duration_seconds': seconds,
        'observation_window': window, 'observation_window_hash': digest(window),
        'denominator': 'Full requested monotonic duration including bootstrap and outages',
        'source_hashes': hashes, 'clock_policy': POLICY,
        'candidate': 'A', 'execution_enabled': False, 'model_loading': False,
        'max_run_storage_bytes': 2 * 1024**3, 'minimum_free_disk_bytes': 2 * 1024**3,
        'created_at_local_utc': datetime.now(UTC).isoformat(), 'python': sys.executable,
        'recovery': 'Failure ends this run; preserve censored labels and start a new run, never backfill fills',
        'sampling': 'ticker_1000ms_not_full_tick_tape'})
    persisted_at = time.perf_counter()
    wait = registration_wait(window, persisted_at)
    atomic_json(out / 'window_registration.json', {
        'observation_window_hash': digest(window), 'persisted_monotonic': persisted_at,
        'preregistration_sha256': sha(out / 'preregistration.json')})
    await asyncio.sleep(wait)
    rules = json.loads((ROOT / 'outputs/dual_regime_v1/exchange_rules.json').read_text())['rules']
    store = ObservationStore(out / 'hybrid_continuous.sqlite3', load_policy(candidate='A'), rules)
    counts = Counter()
    segment = None
    renewal = None
    failure = None
    last_clock = None
    heartbeat_at = 0
    pending = None
    last_seen = {}
    segments = 0
    measurement_attempts = 0
    stop_reason = 'duration_completed'

    def status(state):
        row = store.db.execute('SELECT state FROM observer_checkpoint WHERE id=1').fetchone()
        items = json.loads(row[0])['opportunities'] if row else {}
        return {'state': state, 'elapsed_seconds': time.perf_counter() - started,
                'observed_until_monotonic': time.perf_counter(), 'observation_window_hash': digest(window),
                'requested_seconds': seconds, 'counts': dict(counts), 'clock_segments': segments,
                'opportunities': len(items),
                'fill_statuses': dict(Counter(x['fill_status'] for x in items.values())),
                'label_statuses': dict(Counter(x['label_status'] for x in items.values())),
                'heartbeat_local_utc': datetime.now(UTC).isoformat(), 'failure': failure,
                'last_received_interval': last_clock, 'observer_contract_hash': store.contract,
                'execution_enabled': False, 'uptime_gate_pass': False}

    def process(identity, event):
        event = event | {'observation_window_hash': digest(window)}
        result = store.process(identity, event)
        counts.update(x['reason'] for x in result.get('audit', []) if 'reason' in x)

    def save_segment(samples, new):
        nonlocal segments
        segments += 1
        atomic_json(out / f'clock_{segments:06d}.json', {
            'probes': samples, 'segment': asdict(new), 'segment_id': new.segment_id})

    async def measure(client):
        nonlocal measurement_attempts
        measurement_attempts += 1
        attempt = measurement_attempts
        def record_probe(event):
            index = event.get('index', event.get('sample', {}).get('index'))
            atomic_json(out / f'clock_attempt_{attempt:06d}_probe_{index:02d}.json', event)
        samples = await probes(client, record=record_probe)
        # Preserve rejected calibration inputs, not just successful segments.
        atomic_json(out / f'clock_attempt_{measurement_attempts:06d}.json', {
            'probes': samples, 'policy_hash': digest(POLICY),
            'validation_pending': True, 'source_event_time_modified': False})
        return samples, calibrate(samples)

    try:
        with (out / 'quotes.jsonl').open('x', encoding='utf-8', buffering=1) as quotes, \
                (out / 'closed_bars.jsonl').open('x', encoding='utf-8', buffering=1) as bars_log:
            async with httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False) as client:
                samples, segment = await measure(client)
                save_segment(samples, segment)
                for attempt in range(3):
                    clock = segment.bounds(time.perf_counter(), time.time())
                    five, hourly = await bootstrap(client, SYMBOLS, clock['received_at_lower'])
                    warmup_close = next(iter(five.values()))[-1].start + 300
                    current = segment.bounds(time.perf_counter(), time.time())
                    if warmup_close == int(current['received_at_lower'] // 300) * 300:
                        break
                    counts['bootstrap_boundary_retry_no_signals'] += 1
                else:
                    raise ValueError('Warmup cannot catch current closed boundary')
                last_clock = segment.bounds(time.perf_counter(), time.time())
                process('warmup', {'type': 'warmup', **last_clock,
                        'five': {s: [asdict(b) for b in rows] for s, rows in five.items()},
                        'hourly': {s: {str(t): asdict(b) for t, b in rows.items()} for s, rows in hourly.items()},
                        'availability_basis': 'fetched_now_warmup_only', 'source': REST_URL})
                pending = ClosedBatchQueue(SYMBOLS, warmup_close)
                streams = '/'.join(s.lower() + suffix for s in SYMBOLS for suffix in ('@ticker', '@kline_5m'))
                async with connect(WS_URL + '?streams=' + streams, open_timeout=15,
                                   ping_interval=20, ping_timeout=20, max_queue=16) as ws, \
                        capture_before_cleanup(
                            lambda event: atomic_json(out / 'body_exception.json', event), ROOT):
                    opened = segment.bounds(time.perf_counter(), time.time())
                    if int(opened['received_at_lower'] // 300) * 300 != warmup_close:
                        raise ValueError('WebSocket handoff crossed unobserved closed boundary')
                    while time.perf_counter() - started < seconds:
                        if (out / 'STOP').exists():
                            stop_reason = 'owner_stop'
                            break
                        now = time.perf_counter()
                        if renewal is not None and renewal.done():
                            samples, new = renewal.result()
                            save_segment(samples, new)
                            validate_renewal(segment, new, now, time.time())
                            segment, renewal = new, None
                        if renewal is None and renewal_due(segment, now):
                            renewal = asyncio.create_task(measure(client))
                        clock = segment.bounds(now, time.time())
                        ready = (pending.ready(clock['received_at_lower'], clock['received_at_upper'])
                                 if clock['received_at'] > last_clock['received_at'] else None)
                        if ready is not None:
                            start = ready['start']
                            process('closed:' + str(start), {'type': 'closed_batch', **clock,
                                    'five': ready['five'], 'requires_commit_observation': True,
                                    'inputs_available_at_upper': ready['inputs_available_at_upper'],
                                    'source': 'binance_closed_5m'})
                            last_clock = segment.bounds(time.perf_counter(), time.time())
                            process('commit:' + str(start), {'type': 'commit_observed', **last_clock,
                                    'signal_time': start + 300})
                            pending.committed(start)
                        if now - heartbeat_at >= 10:
                            used = sum(p.stat().st_size for p in out.iterdir() if p.is_file())
                            if used >= 2 * 1024**3 or shutil.disk_usage(out).free < 2 * 1024**3:
                                raise ValueError('Independent observation storage budget exhausted')
                            publish_status(out / 'status.json', status('RUNNING'))
                            heartbeat_at = now
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=min(2, seconds - (now - started)))
                        except asyncio.TimeoutError:
                            clock = segment.bounds(time.perf_counter(), time.time())
                            if clock['received_at'] > last_clock['received_at']:
                                process('clock:' + digest(clock), {'type': 'clock', **clock})
                                last_clock = clock
                            continue
                        clock = segment.bounds(time.perf_counter(), time.time())
                        message = json.loads(raw)
                        data = message.get('data', {})
                        if clock['received_at'] <= last_clock['received_at']:
                            counts['renewal_receipt_order_uncertain'] += 1
                            continue
                        last_clock = clock
                        if message.get('stream', '').endswith('@ticker'):
                            event = normalize_ticker(message, clock['received_at_upper']) | clock
                            native = native_ms(data['E'])
                            if event['source_time'] != native:
                                raise ValueError('Native source time changed')
                            reason = segment.check_quote(native, clock)
                            event.update(source_event_time_native_ms=data['E'], clock_validation=reason)
                            quotes.write(json.dumps(event, sort_keys=True, allow_nan=False) + '\n')
                            counts[reason] += 1
                            symbol = event['symbol']
                            if symbol in last_seen and native - last_seen[symbol] > 30:
                                process('gap:' + digest(event), {'type': 'disconnect', **clock, 'reason': 'native_quote_gap'})
                            last_seen[symbol] = max(native, last_seen.get(symbol, native))
                            if reason == 'qualified_time_interval':
                                process('quote:' + symbol + ':' + str(data['E']), event)
                        elif data.get('k', {}).get('x') is True:
                            k = data['k']
                            symbol = data.get('s')
                            if symbol not in SYMBOLS or k.get('i') != '5m':
                                continue
                            bar = _bar(k['t'], [k[x] for x in ('o', 'h', 'l', 'c', 'v')], 300)
                            if k['T'] != (bar.start + 300) * 1000 - 1:
                                raise ValueError('Invalid bar boundary')
                            if bar.start + 300 > clock['received_at_lower']:
                                counts['closed_bar_receipt_order_deferred'] += 1
                            bars_log.write(json.dumps({'symbol': symbol, 'bar': asdict(bar),
                                           **clock}, sort_keys=True, allow_nan=False) + '\n')
                            if not pending.add(symbol, asdict(bar), clock['received_at_upper']):
                                counts['duplicate_or_pre_observation_bar'] += 1
    except Exception as exc:
        failure = {'type': type(exc).__name__, 'reason': 'Observation stopped; no timestamp or rule relaxation'}
        failure['exception_observed_monotonic'] = time.perf_counter()
        failure['exception_observed_local_utc_epoch'] = time.time()
        failure['timestamp_scope'] = 'EXCEPTION_HANDLER_ENTRY_NOT_SOURCE_EVENT'
        failure['source_locations'] = failure_frames(exc, ROOT)
        if isinstance(exc, OSError):
            failure['io_detail'] = io_failure_detail(exc, out)
        if type(exc).__name__.startswith('ConnectionClosed'):
            failure['websocket_close'] = connection_failure_detail(exc)
        if isinstance(exc, ValueError):
            failure['contract_detail'] = str(exc)
        stop_reason = 'observation_failed'
    finally:
        cleanup = await cancel_renewal(renewal)
        if cleanup['state'] == 'TIMED_OUT':
            failure = failure or {'type': 'RenewalCleanupTimeout',
                                  'reason': 'Renewal cancellation did not finish; no restart authorized'}
            stop_reason = 'observation_failed'
        if last_clock is not None:
            try:
                process('end', {'type': 'observation_end', **last_clock, 'reason': stop_reason})
            except Exception as exc:
                failure = failure or {'type': type(exc).__name__, 'reason': 'Final censor transaction failed'}
        report = status('FAILED' if failure else 'STOPPED' if stop_reason == 'owner_stop' else 'COMPLETED')
        report['stop_reason'] = stop_reason
        report['renewal_cleanup'] = cleanup
        atomic_json(out / 'report.json', report)
        try:
            publish_status(out / 'status.json', report)
        except OSError as exc:
            failure = failure or {'type': type(exc).__name__,
                'reason': 'Terminal status publication failed', 'io_detail': io_failure_detail(exc, out)}
            report.update(state='FAILED', failure=failure)
            atomic_json(out / 'report.json', report)
            atomic_json(out / 'status_publish_failure.json', failure)
        store.close()
        print(json.dumps(report), flush=True)
    return 1 if failure else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--seconds', type=int, default=86400)
    args = parser.parse_args()
    if not 30 <= args.seconds <= 259200:
        raise ValueError('Explicit observation duration must be 30 seconds to 72 hours')
    out = (ROOT / args.output).resolve()
    if not out.is_relative_to(ROOT / 'outputs/hybrid_regime_v1'):
        raise ValueError('Independent new observer directory required')
    lock = ROOT / 'work/hybrid_delivery/continuous_public_observer.lock'
    lock.parent.mkdir(parents=True, exist_ok=True)
    with _process_lock(lock):
        out.mkdir(parents=True, exist_ok=False)
        return asyncio.run(observe(out, args.seconds))


if __name__ == '__main__':
    sys.exit(main())
