from copy import deepcopy
from datetime import datetime, timedelta, timezone
from itertools import product

import pytest

from kquant import options_minute_admission as candidate
from prepared_minutes import PreparedMinute


START = datetime(2026, 10, 22, 13, 30, tzinfo=timezone.utc)


def minute():
    return dict(symbol='TEST', interval='1m', closed=True, open_at=START.isoformat(),
        available_at=(START+timedelta(minutes=1)).isoformat(),
        received_at=(START+timedelta(minutes=1, seconds=1)).isoformat(),
        open=100, high=102, low=99, close=101, turnover=1000, volume=10,
        turnover_source='NATIVE', currency='USD', sdk_evidence={'adjustment':'NoAdjust'})


def variants():
    rows = [minute()]
    for key in ('open_at','available_at','received_at','symbol','interval','closed',
                'open','high','low','close','turnover','volume','currency','turnover_source'):
        missing = minute()
        missing.pop(key)
        rows.append(missing)
        for value in (None, '', False, -1, 0, 101):
            changed = minute()
            changed[key] = value
            rows.append(changed)
    for field, values in [('adjustment', ['AdjustForward','NoAdjust','NOT_PROVIDED',None]),
                          ('trade_session', ['Pre','Regular','Intraday',0,None])]:
        for value in values:
            changed = minute()
            changed['sdk_evidence'][field] = value
            rows.append(changed)
    for field in ('open_at','available_at','received_at'):
        for seconds in (-61, -1, 0, 59, 60, 61, 62):
            changed = minute()
            changed[field] = (START+timedelta(seconds=seconds)).isoformat()
            rows.append(changed)
    return rows


def test_original_validator_equivalence_across_content_and_live_context():
    checked = 0
    contexts = product(('TEST','OTHER'), (-1,0,1), (60,120), (0,58,59,60,61,62,63,86400), (True,False))
    contexts = list(contexts)
    for raw in variants():
        prepared = PreparedMinute(raw)
        before = deepcopy(raw)
        for symbol, opening_seconds, until_seconds, now_seconds, price_only in contexts:
            kwargs = dict(symbol=symbol, opening=START+timedelta(seconds=opening_seconds),
                until=START+timedelta(seconds=until_seconds), now=START+timedelta(seconds=now_seconds),
                price_only=price_only)
            assert candidate.classify(prepared, **kwargs) == candidate.parent.classify(raw, **kwargs)
            checked += 1
        assert raw == before
    assert checked >= 20000


def test_live_time_does_not_inherit_cached_admission():
    value = PreparedMinute(minute())
    kwargs = dict(symbol='TEST', opening=START, until=START+timedelta(minutes=1))
    assert candidate.classify(value, **kwargs, now=START+timedelta(seconds=60))[1] == 'MINUTE_TIME_EVIDENCE_CONFLICT'
    assert candidate.classify(value, **kwargs, now=START+timedelta(seconds=61))[1] is None
    with pytest.raises(TypeError):
        value._native_structure = None


def test_changed_validator_does_not_reuse_old_structure(monkeypatch):
    value = PreparedMinute(minute())
    monkeypatch.setattr(candidate.parent, 'classify', lambda *args, **kwargs: (START,'TEST_ONLY_CHANGED_POLICY'))
    assert candidate.classify(value, symbol='TEST', opening=START,
        until=START+timedelta(minutes=1), now=START+timedelta(seconds=62))[1] == 'TEST_ONLY_CHANGED_POLICY'


def test_partition_preserves_original_raw_rejected_and_eligible():
    rows = []
    for row in variants():
        try:
            candidate.parent.common.timestamp(row['received_at'])
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        rows.append(row)
    kwargs = dict(symbol='TEST', opening=START, until=START+timedelta(minutes=2),
                  now=START+timedelta(seconds=62))
    assert candidate.partition([PreparedMinute(row) for row in rows], **kwargs) == candidate.parent.partition(rows, **kwargs)


def test_missing_native_time_blocks_without_aborting_other_rows():
    broken = minute()
    broken['received_at'] = None
    rows = [PreparedMinute(broken), PreparedMinute(minute())]
    result = candidate.partition(rows, symbol='TEST', opening=START,
        until=START+timedelta(minutes=1), now=START+timedelta(seconds=62))
    assert len(result['eligible']) == 1
    assert rows[0].identity not in result['eligible']
