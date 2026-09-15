import pytest
from kquant_crypto.hybrid_order_count_audit import audit_order_count


def check(snapshot, limit=3):
    return audit_order_count(symbol='BTCUSDT',limit=limit,snapshot=snapshot,now=100,max_age=5)


def valid():
    return dict(symbol='BTCUSDT',available_at=99,open_orders=1,reserved_new_orders=1,
                includes_algo_orders=True,reconciled=True)


def test_reserved_orders_are_counted_without_granting_access():
    assert not check(valid())['blockers']
    assert not check(valid())['account_verified']
    assert 'ORDER_COUNT_LIMIT_EXCEEDED' in check(valid(),limit=2)['blockers']


@pytest.mark.parametrize('field,value,reason',[
    ('symbol','ETHUSDT','ORDER_COUNT_SYMBOL_MISMATCH'),
    ('available_at',101,'ORDER_COUNT_STALE_OR_FUTURE'),
    ('available_at',90,'ORDER_COUNT_STALE_OR_FUTURE'),
    ('reserved_new_orders',None,'ORDER_COUNT_INCOMPLETE'),
    ('open_orders',True,'ORDER_COUNT_INCOMPLETE'),
    ('includes_algo_orders',False,'ALGO_ORDER_COUNT_UNCONFIRMED'),
    ('reconciled',False,'ORDER_COUNT_NOT_RECONCILED')])
def test_unknown_or_mismatched_counts_block(field,value,reason):
    item=valid()
    item[field]=value
    assert reason in check(item)['blockers']


def test_missing_is_not_zero():
    assert check(None)['blockers'] == ['ORDER_COUNT_UNAVAILABLE']


def test_negative_clock_cannot_become_fresh_by_subtraction():
    item=valid()
    item['available_at']=-1
    with pytest.raises(ValueError):
        audit_order_count(symbol='BTCUSDT',limit=3,snapshot=item,now=-1,max_age=5)
    result=audit_order_count(symbol='BTCUSDT',limit=3,snapshot=item,now=0,max_age=5)
    assert 'ORDER_COUNT_STALE_OR_FUTURE' in result['blockers']
