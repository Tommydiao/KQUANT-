"""Explicit sampling semantics; never upgrades old quotes or changes execution."""
from __future__ import annotations
import math

SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')
CONTRACT = {
    'version': 'hybrid_ticker_semantics_v1_2',
    'quote_observation_granularity': '1000ms_24hr_ticker_sample',
    'source_event_time_meaning': 'message_event_time_not_price_level_change_time',
    'price_change_time_known': False,
    'execution_quality': 'QUOTE_AWARE_SAMPLED_SIMULATION_NOT_EXCHANGE_FILL',
    'complete_book_sequence': False,
    'full_size_execution_guaranteed': False,
    'freshness_seconds': 30,
    'official_source': 'https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md',
    'review_date': '2026-09-06',
}


def describe_quote(q):
    """Read-only semantic projection. Input is never repaired or mutated."""
    reasons = []
    if q.get('symbol') not in SYMBOLS or q.get('market_type') != 'spot':
        reasons.append('wrong_instrument')
    native = q.get('source_event_time_native_ms')
    if type(native) is not int or not 10**12 <= native < 10**13:
        reasons.append('missing_native_message_event_time')
    elif native / 1000 != q.get('source_time'):
        reasons.append('source_time_changed')
    if q.get('stream') != str(q.get('symbol', '')).lower() + '@ticker':
        reasons.append('not_registered_ticker_stream')
    keys = ('bid','ask','bid_size','ask_size','received_at_lower','received_at_upper')
    valid = all(type(q.get(k)) in (int, float) and math.isfinite(q[k]) and q[k] > 0 for k in keys)
    if not valid:
        reasons.append('missing_or_invalid_quote_fields')
    else:
        if q['bid'] > q['ask']:
            reasons.append('crossed_quote')
        lo, hi = q['received_at_lower'], q['received_at_upper']
        if hi < lo or hi - lo > 1:
            reasons.append('receiver_interval_invalid')
        if type(native) is int:
            if native / 1000 > lo:
                reasons.append('receipt_order_uncertain')
            if hi - native / 1000 > CONTRACT['freshness_seconds']:
                reasons.append('stale_quote')
    if not q.get('clock_segment_id') or q.get('source_event_time_modified') is not False:
        reasons.append('unproven_clock_provenance')
    return {'contract': CONTRACT, 'eligible_sample': not reasons, 'reasons': reasons,
            'raw_payload_hash': q.get('raw_payload_hash'), 'clock_segment_id': q.get('clock_segment_id'),
            'strict_price_change_evidence': False, 'exchange_execution_evidence': False}


def covered_seconds(intervals, start, end):
    """Union within a predeclared observation window, never a message denominator."""
    if not all(math.isfinite(v) for v in (start, end)) or end <= start:
        raise ValueError('Explicit planned observation window required')
    clipped = []
    for a,b in intervals:
        if not all(math.isfinite(v) for v in (a,b)) or b < a:
            raise ValueError('Invalid coverage interval')
        a,b = max(start,a),min(end,b)
        if b > a: clipped.append((a,b))
    covered, until = 0., start
    for a,b in sorted(clipped):
        covered += max(0., b - max(until,a))
        until = max(until,b)
    return {'qualified_seconds':covered, 'scheduled_seconds':end-start,
            'fraction':covered/(end-start)}
