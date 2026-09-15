import pytest
from kquant_crypto.hybrid_reference_price_audit import audit_percent_price

RULE={'filterType':'PERCENT_PRICE_BY_SIDE','bidMultiplierDown':'.9','bidMultiplierUp':'1.1',
      'askMultiplierDown':'.8','askMultiplierUp':'1.2','avgPriceMins':5}


def check(ref, price='115',side='BUY'):
    return audit_percent_price(RULE,symbol='BTCUSDT',side=side,price=price,reference=ref,now=100,max_age=5)


def test_side_and_expiry():
    ref=dict(symbol='BTCUSDT',available_at=99,kind='EXCHANGE_REFERENCE_PRICE',value='100')
    assert check(ref)==['PERCENT_PRICE_VIOLATION']
    assert not check(ref,side='SELL')
    ref['available_at']=101
    assert check(ref)==['REFERENCE_PRICE_STALE_OR_FUTURE']


def test_fallback_requires_absence_and_window():
    ref=dict(symbol='BTCUSDT',available_at=99,kind='WEIGHTED_AVERAGE',value='100',avgPriceMins=5)
    assert check(ref)==['REFERENCE_SELECTION_UNCONFIRMED']
    ref['exchange_reference_absent']=True
    assert not check(ref,price='100')
    ref['avgPriceMins']=1
    assert check(ref)==['REFERENCE_WINDOW_MISMATCH']


def test_boolean_window_cannot_equal_one_minute():
    rule=dict(RULE,avgPriceMins=1)
    ref=dict(symbol='BTCUSDT',available_at=99,kind='WEIGHTED_AVERAGE',value='100',
             exchange_reference_absent=True,avgPriceMins=True)
    assert audit_percent_price(rule,symbol='BTCUSDT',side='BUY',price='100',reference=ref,now=100,max_age=5)==['REFERENCE_WINDOW_MISMATCH']


def test_negative_clock_rejected():
    with pytest.raises(ValueError):
        audit_percent_price(RULE,symbol='BTCUSDT',side='BUY',price='100',reference=None,now=-1,max_age=5)
