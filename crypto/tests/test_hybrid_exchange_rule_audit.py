import pytest
from kquant_crypto.hybrid_exchange_rule_audit import audit_symbol, audit_limit_ioc


def payload(filters):
    return {'symbols':[{'symbol':'BTCUSDT','status':'TRADING','isSpotTradingAllowed':True,'filters':filters}]}


def test_missing_not_defaulted_to_zero():
    result = audit_symbol(payload([]),'BTCUSDT')
    assert 'MISSING:PRICE_FILTER' in result['blockers']
    assert not result['execution_allowed']


def test_zero_price_filter_preserved_not_missing():
    item = {'filterType':'PRICE_FILTER','minPrice':'0','maxPrice':'0','tickSize':'0'}
    result = audit_symbol(payload([item]),'BTCUSDT')
    assert result['raw_filters']['PRICE_FILTER'] == item
    assert 'MISSING:PRICE_FILTER' not in result['blockers']


def test_duplicate_rejected_and_unknown_preserved():
    item = {'filterType':'NEW_FILTER','limit':5}
    with pytest.raises(ValueError):
        audit_symbol(payload([item,item]),'BTCUSDT')
    result = audit_symbol(payload([item]),'BTCUSDT')
    assert 'REQUIRES_CONTEXT_OR_IMPLEMENTATION:NEW_FILTER' in result['blockers']
    assert result['raw_filters']['NEW_FILTER'] == item


def test_limit_ioc_applies_exact_filters_without_rounding():
    data = payload([
        {'filterType':'PRICE_FILTER','minPrice':'0','maxPrice':'1000','tickSize':'.01'},
        {'filterType':'LOT_SIZE','minQty':'.001','maxQty':'10','stepSize':'.001'},
        {'filterType':'NOTIONAL','minNotional':'5','maxNotional':'10000'},
        {'filterType':'MARKET_LOT_SIZE'}, {'filterType':'PERCENT_PRICE_BY_SIDE'}])
    result = audit_limit_ioc(data,'BTCUSDT',price='100.001',quantity='.0101')
    assert 'PRICE_FILTER_VIOLATION' in result['blockers']
    assert 'LOT_SIZE_VIOLATION' in result['blockers']
    assert 'NOTIONAL_VIOLATION:NOTIONAL' in result['blockers']
    assert 'MARKET_LOT_SIZE' in result['not_applicable']
    assert 'CONTEXT_OR_IMPLEMENTATION_REQUIRED:PERCENT_PRICE_BY_SIDE' in result['blockers']
    assert not result['execution_allowed']


def test_exchange_constraints_and_limit_support_not_ignored():
    data = payload([])
    data['exchangeFilters'] = [{'filterType':'EXCHANGE_MAX_NUM_ORDERS','maxNumOrders':100}]
    result = audit_limit_ioc(data,'BTCUSDT',price='100',quantity='1')
    assert 'LIMIT_ORDER_SUPPORT_UNCONFIRMED' in result['blockers']
    assert 'EXCHANGE_CONTEXT_REQUIRED:EXCHANGE_MAX_NUM_ORDERS' in result['blockers']
    assert result['raw_exchange_filters'] == data['exchangeFilters']
    data['exchangeFilters'].append(data['exchangeFilters'][0])
    with pytest.raises(ValueError):
        audit_limit_ioc(data,'BTCUSDT',price='100',quantity='1')


def test_order_count_contract_is_used_in_ioc_audit():
    data = payload([{'filterType':'MAX_NUM_ORDERS','maxNumOrders':2}])
    snapshot = dict(symbol='BTCUSDT',available_at=99,open_orders=1,reserved_new_orders=1,
                    includes_algo_orders=True,reconciled=True)
    result = audit_limit_ioc(data,'BTCUSDT',price='100',quantity='1',
                             order_count=snapshot,now=100,max_count_age=5)
    assert 'ORDER_COUNT_LIMIT_EXCEEDED' in result['blockers']
    snapshot['reserved_new_orders'] = 0
    result = audit_limit_ioc(data,'BTCUSDT',price='100',quantity='1',
                             order_count=snapshot,now=100,max_count_age=5)
    assert 'ORDER_COUNT_LIMIT_EXCEEDED' not in result['blockers']
    assert not result['execution_allowed']


def test_specialized_limits_not_applied_to_plain_new_ioc():
    names=['MAX_NUM_ALGO_ORDERS','MAX_NUM_ORDER_LISTS','MAX_NUM_ORDER_AMENDS']
    data=payload([{'filterType':name} for name in names])
    result=audit_limit_ioc(data,'BTCUSDT',price='100',quantity='1')
    assert set(names) <= set(result['not_applicable'])
    assert not result['protection_order_validation_included']
    assert not result['execution_allowed']
