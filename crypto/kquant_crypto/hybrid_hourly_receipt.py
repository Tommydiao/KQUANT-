"""Native UTC spot kline to isolated factor input; never creates fill evidence."""
import math

from .hybrid_clock import digest, native_ms

SYMBOLS = {'BTCUSDT', 'ETHUSDT', 'SOLUSDT'}
VERSION = 'native_hourly_receipt_dev_v1'


def normalize_hourly(message, segment, *, monotonic_at, local_at):
    """Validate native ms fields against existing calibrated receipt intervals.

    The journal uses integer seconds; availability rounds UP, never backwards.
    Accepted event payloads retain receipt provenance in the journal transaction.
    """
    audit = dict(version=VERSION, scope='DEV_ONLY', accepted=False,
                 execution_enabled=False, quote_evidence=False,
                 raw_message_hash=digest(message))
    try:
        receipt = segment.bounds(monotonic_at, local_at)
        audit['receipt'] = receipt
        data = message.get('data', message)
        k = data['k']
        symbol = data['s']
        if data['e'] != 'kline' or symbol not in SYMBOLS or k['s'] != symbol:
            raise ValueError('wrong_instrument_or_event')
        if 'stream' in message and message['stream'] != symbol.lower()+'@kline_1h':
            raise ValueError('wrong_stream')
        if k['i'] != '1h' or k['x'] is not True:
            raise ValueError('not_closed_utc_hour')
        start = native_ms(k['t'])
        end_inclusive = native_ms(k['T'])
        source_time = native_ms(data['E'])
        audit['source_event_time_native_ms'] = data['E']
        audit['source_event_time'] = source_time
        if k['t'] % 3600000 or k['T'] != k['t']+3600000-1:
            raise ValueError('invalid_hour_boundary')
        if source_time < end_inclusive or receipt['received_at_lower'] < start+3600:
            raise ValueError('event_or_receipt_precedes_close')
        reason = segment.check_quote(source_time, receipt)
        if reason != 'qualified_time_interval':
            raise ValueError(reason)
        values = [float(k[key]) for key in ('o', 'h', 'l', 'c', 'v')]
        o, h, low, c, volume = values
        if (not all(math.isfinite(v) for v in values) or min(o,h,low,c) <= 0
                or volume < 0 or not low <= min(o,c) <= max(o,c) <= h):
            raise ValueError('invalid_ohlcv')
        event = dict(event_id=f'binance_spot_1h:{symbol}:{k["t"]}', payload=dict(
            kind='ingest', symbol=symbol,
            bar=dict(start=int(start), open=o, high=h, low=low, close=c, volume=volume),
            received_at=math.ceil(receipt['received_at_upper']), closed=True,
            provenance=dict(source_event_time_native_ms=data['E'], receipt=receipt,
                            raw_message_hash=audit['raw_message_hash'], adapter_version=VERSION,
                            quote_evidence=False)))
        audit.update(accepted=True, reason='qualified_closed_hour', event=event,
                     event_hash=digest(event), availability_basis='OBSERVED_RECEIPT')
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        audit['reason'] = str(exc)
    return audit
