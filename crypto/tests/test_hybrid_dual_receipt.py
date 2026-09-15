import copy
from dataclasses import replace

import pytest

from kquant_crypto.hybrid_clock import ClockSegment, POLICY, digest
from kquant_crypto.hybrid_dual_receipt import normalize_closed, renewal_overlap

START = 1754006400000


def fixture(interval):
    duration = 300 if interval == '5m' else 3600
    close = START/1000+duration
    clock = ClockSegment(close-100+.1, close-100+.2, 100, close, 'probe', digest(POLICY))
    msg = dict(stream='btcusdt@kline_'+interval, data=dict(e='kline', s='BTCUSDT', E=int((close+.5)*1000),
        k=dict(s='BTCUSDT', i=interval, t=START, T=START+duration*1000-1, x=True,
               o='100', h='102', l='99', c='101', v='20')))
    return msg, clock, close


@pytest.mark.parametrize('interval', ['5m', '1h'])
def test_native_closed_and_availability(interval):
    msg, clock, close = fixture(interval)
    before = copy.deepcopy(msg)
    result = normalize_closed(msg, clock, monotonic_at=101, local_at=close+1)
    assert result['accepted'] and result['close_time'] == close
    assert result['available_at'] == close+2
    assert result['source_event_time_native_ms'] == msg['data']['E']
    assert not result['quote_evidence'] and not result['execution_enabled']
    assert msg == before


@pytest.mark.parametrize('change', ['forming', 'unit', 'future', 'boundary', 'stream', 'nan', 'missing'])
def test_bad_contract_rejected(change):
    msg, clock, close = fixture('5m')
    if change == 'forming': msg['data']['k']['x'] = False
    if change == 'unit': msg['data']['E'] *= 1000
    if change == 'future': msg['data']['E'] += 10000
    if change == 'boundary': msg['data']['k']['T'] += 1
    if change == 'stream': msg['stream'] = 'btcusdt@kline_1h'
    if change == 'nan': msg['data']['k']['c'] = 'nan'
    if change == 'missing': del msg['data']['E']
    result = normalize_closed(msg, clock, monotonic_at=101, local_at=close+1)
    assert not result['accepted']
    assert 'bar' not in result
    if change == 'forming': assert result['reason'] == 'forming_bar'


def test_stale_not_relaxed():
    msg, clock, close = fixture('5m')
    assert normalize_closed(msg, clock, monotonic_at=420, local_at=close+320)['reason'] == 'stale_quote'


def test_renewal_cannot_hide_clock_discontinuity():
    _, clock, close = fixture('1h')
    assert renewal_overlap(clock, clock, monotonic_at=101, local_at=close+1)
    shifted = replace(clock, offset_lower=clock.offset_lower+2, offset_upper=clock.offset_upper+2)
    assert not renewal_overlap(clock, shifted, monotonic_at=101, local_at=close+1)
    with pytest.raises(ValueError, match='discontinuity'):
        renewal_overlap(clock, clock, monotonic_at=101, local_at=close+321)
    with pytest.raises(ValueError, match='expired'):
        renewal_overlap(clock, clock, monotonic_at=701, local_at=close+601)
