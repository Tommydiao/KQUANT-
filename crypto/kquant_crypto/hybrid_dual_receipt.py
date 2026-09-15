"""Isolated native UTC closed-bar contract; not quote or execution evidence."""
import math

from .hybrid_clock import digest, native_ms
from .hybrid_hourly_receipt import SYMBOLS

INTERVALS = {'5m': 300, '1h': 3600}
VERSION = 'native_dual_receipt_dev_v1'


def normalize_closed(message, segment, *, monotonic_at, local_at):
    result = dict(version=VERSION, accepted=False, execution_enabled=False,
                  quote_evidence=False, scope='DEV_ONLY')
    try:
        result['raw_message_hash'] = digest(message)
        receipt = segment.bounds(monotonic_at, local_at)
        result['receipt'] = receipt
        data = message.get('data', message)
        k = data['k']
        symbol, interval = data['s'], k['i']
        if data['e'] != 'kline' or symbol not in SYMBOLS or k['s'] != symbol:
            raise ValueError('wrong_instrument_or_event')
        if interval not in INTERVALS:
            raise ValueError('unsupported_interval')
        if message.get('stream', symbol.lower()+'@kline_'+interval) != symbol.lower()+'@kline_'+interval:
            raise ValueError('wrong_stream')
        if type(k['x']) is not bool:
            raise ValueError('invalid_closed_flag')
        if not k['x']:
            raise ValueError('forming_bar')
        duration = INTERVALS[interval]
        start, end, source = native_ms(k['t']), native_ms(k['T']), native_ms(data['E'])
        result['source_event_time_native_ms'] = data['E']
        if k['t'] % (duration*1000) or k['T'] != k['t']+duration*1000-1:
            raise ValueError('invalid_bar_boundary')
        if source < end or receipt['received_at_lower'] < start+duration:
            raise ValueError('event_or_receipt_precedes_close')
        reason = segment.check_quote(source, receipt)
        if reason != 'qualified_time_interval':
            raise ValueError(reason)
        o, h, low, c, volume = (float(k[key]) for key in ('o', 'h', 'l', 'c', 'v'))
        if (not all(math.isfinite(v) for v in (o,h,low,c,volume)) or min(o,h,low,c) <= 0
                or volume < 0 or not low <= min(o,c) <= max(o,c) <= h):
            raise ValueError('invalid_ohlcv')
        result.update(accepted=True, reason='qualified_closed_bar', symbol=symbol,
                      interval=interval, event_id=f'binance_spot_{interval}:{symbol}:{k["t"]}',
                      close_time=int(start)+duration, available_at=math.ceil(receipt['received_at_upper']),
                      bar=dict(start=int(start), open=o, high=h, low=low, close=c, volume=volume))
    except (ValueError, KeyError, TypeError, OverflowError, AttributeError) as exc:
        result['reason'] = str(exc)
    return result


def renewal_overlap(old, new, *, monotonic_at, local_at):
    """Expired, discontinuous or disjoint mappings cannot bridge observation runs."""
    a = old.bounds(monotonic_at, local_at)
    b = new.bounds(monotonic_at, local_at)
    return max(a['received_at_lower'], b['received_at_lower']) <= min(
        a['received_at_upper'], b['received_at_upper'])
