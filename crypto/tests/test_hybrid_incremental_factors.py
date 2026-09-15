from types import SimpleNamespace

import pytest

from kquant_crypto.hybrid_incremental_factors import IncrementalFactors
from kquant_crypto.hybrid_multifactor_dev import CORE_SYMBOLS


def bar(start=0, close=101):
    return SimpleNamespace(start=start, open=100, high=105, low=95,
                           close=close, volume=1000)


def engine(**kwargs):
    return IncrementalFactors(3600, receipt_basis='REPLAY_CLOCK_FIXTURE',
                              source='fixture', **kwargs)


def enqueue(e, start=0, receipt=None):
    for symbol in reversed(CORE_SYMBOLS):
        e.ingest(symbol, bar(start), received_at=receipt or start+3601, closed=True)


def test_receipt_and_missing_peer_block_consumption():
    e = engine()
    for s in CORE_SYMBOLS[:2]:
        e.ingest(s, bar(), received_at=3601, closed=True)
    assert e.advance(3602) == []
    e.ingest(CORE_SYMBOLS[2], bar(), received_at=3610, closed=True)
    assert e.advance(3609) == []
    rows = e.advance(3610)
    assert len(rows) == 3
    assert all(r['received_at'] == 3610 for r in rows)
    assert all(f['available_at'] == 3610 for r in rows for f in r['factor_contract']['factors'])
    assert e.advance(3610) == []


def test_duplicate_and_correction_never_rewrite():
    e = engine()
    enqueue(e)
    s = CORE_SYMBOLS[0]
    assert e.ingest(s, bar(), received_at=3605, closed=True) == 'DUPLICATE'
    with pytest.raises(ValueError, match='Conflicting'):
        e.ingest(s, bar(close=102), received_at=3605, closed=True)
    e.advance(3605)
    digest = e.digest
    assert e.ingest(s, bar(), received_at=3606, closed=True) == 'ALREADY_CONSUMED_NO_REWRITE'
    with pytest.raises(ValueError, match='Consumed'):
        e.ingest(s, bar(close=102), received_at=3606, closed=True)
    assert e.digest == digest


def test_out_of_order_waits_and_replays_deterministically():
    a, b = engine(), engine()
    enqueue(a, 3600)
    assert a.advance(7201) == []
    enqueue(a)
    rows_a = a.advance(7201)
    enqueue(b)
    enqueue(b, 3600)
    assert rows_a == b.advance(7201)
    assert [r['as_of'] for r in rows_a] == [3600]*3 + [7200]*3


@pytest.mark.parametrize('closed,receipt', [(False, 3601), (True, 3599)])
def test_forming_and_preclose_receipt_rejected(closed, receipt):
    with pytest.raises(ValueError):
        engine().ingest(CORE_SYMBOLS[0], bar(), received_at=receipt, closed=closed)


def test_bounded_queue_and_monotonic_clock():
    e = engine(max_pending_hours=1)
    with pytest.raises(ValueError, match='Bounded'):
        enqueue(e, 3600)
    e.advance(3601)
    with pytest.raises(ValueError, match='monotone'):
        e.advance(3600)


def test_future_inputs_do_not_change_frozen_snapshot():
    a, b = engine(), engine()
    enqueue(a)
    enqueue(b)
    enqueue(b, 3600)
    assert a.advance(3601) == b.advance(3601)
