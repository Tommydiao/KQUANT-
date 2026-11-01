from datetime import UTC, datetime, timedelta

import pytest

from prepared_minutes import PreparedMinute, PriceBlockPreparation
from kquant.options_opening_momentum import price_aggregate


def rows(count=55):
    start = datetime(2026, 10, 22, 13, 30, tzinfo=UTC)
    return [dict(symbol='TEST', open_at=(start + timedelta(minutes=i)).isoformat(),
                 available_at=(start + timedelta(minutes=i+1)).isoformat(),
                 received_at=(start + timedelta(minutes=i+1, seconds=1)).isoformat(),
                 open=10+i, high=12+i, low=9+i, close=11+i)
            for i in range(count)]


def test_all_eleven_prefixes_use_original_aggregation_and_reuse_blocks():
    raw = rows()
    prepared = [PreparedMinute(row) for row in raw]
    pool = PriceBlockPreparation()
    calls = []
    def original(group):
        calls.append(group)
        return price_aggregate(group)
    for count in range(5, 60, 5):
        assert pool.aggregate(prepared[:count], original) == price_aggregate(raw[:count])
    assert len(calls) == 11  # Not 1+2+...+11 repeated blocks.
    with pytest.raises(TypeError):
        pool.aggregate(prepared, original)[0]['close'] = 0


@pytest.mark.parametrize('field,value', [('close', 20), ('received_at', '2026-10-22T13:31:03+00:00'),
                                        ('source_semantics', {'version': 2})])
def test_revised_content_cannot_reuse_old_block(field, value):
    raw = rows(5)
    pool = PriceBlockPreparation()
    original = pool.aggregate([PreparedMinute(r) for r in raw], price_aggregate)
    raw[0][field] = value
    revised = pool.aggregate([PreparedMinute(r) for r in raw], price_aggregate)
    assert revised == price_aggregate(raw)
    assert revised != original
    assert len(pool.entries) == 2


def test_mutable_rows_and_replacement_function_are_not_reused():
    raw = rows(6)
    pool = PriceBlockPreparation(bound=1)
    assert pool.aggregate(raw, price_aggregate) == price_aggregate(raw)
    raw[0]['close'] = 99
    assert pool.aggregate(raw, price_aggregate) == price_aggregate(raw)
    assert not pool.entries
    prepared = [PreparedMinute(r) for r in raw]
    pool.aggregate(prepared, price_aggregate)
    def replacement(group):
        return [{'replacement': True}]
    assert pool.aggregate(prepared, replacement) == [{'replacement': True}]
    assert len(pool.entries) == 1


def test_missing_live_admission_never_uses_cached_aggregate(monkeypatch):
    import first_hour
    raw = rows(5)
    prepared = [PreparedMinute(r) for r in raw]
    arguments = dict(symbol='TEST', bars=prepared, opening=None, checkpoint=None, now=None)
    monkeypatch.setattr(first_hour.trend, 'complete_minutes', lambda *a, **k: (prepared, []))
    assert first_hour.prepare_inputs(**arguments)[3] == price_aggregate(raw)
    monkeypatch.setattr(first_hour.trend, 'complete_minutes', lambda *a, **k: ([], ['SOURCE_CONFLICT']))
    assert first_hour.prepare_inputs(**arguments)[1:] == (['SOURCE_CONFLICT'], {}, [])
