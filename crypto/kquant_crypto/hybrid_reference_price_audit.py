"""Explicit reference-price input contract for read-only filter evaluation."""
from .hybrid_mock_broker import decimal, exact_decimal


@exact_decimal
def audit_percent_price(rule, *, symbol, side, price, reference, now, max_age):
    if side not in ('BUY','SELL') or type(now) is not int or now < 0 or type(max_age) is not int or max_age < 0:
        raise ValueError('Explicit side and clock policy required')
    if not isinstance(reference,dict):
        return ['REFERENCE_PRICE_UNAVAILABLE']
    if reference.get('symbol') != symbol:
        return ['REFERENCE_PRICE_SYMBOL_MISMATCH']
    at=reference.get('available_at')
    if type(at) is not int or at < 0 or not 0 <= now-at <= max_age:
        return ['REFERENCE_PRICE_STALE_OR_FUTURE']
    kind=reference.get('kind')
    if kind != 'EXCHANGE_REFERENCE_PRICE':
        if kind != 'WEIGHTED_AVERAGE' or reference.get('exchange_reference_absent') is not True:
            return ['REFERENCE_SELECTION_UNCONFIRMED']
        window = reference.get('avgPriceMins')
        rule_window = rule.get('avgPriceMins')
        if type(window) is not int or type(rule_window) is not int or window < 0 or window != rule_window:
            return ['REFERENCE_WINDOW_MISMATCH']
    value=decimal(reference['value'])
    p=decimal(price)
    if value <= 0 or p <= 0:
        raise ValueError('Positive prices required')
    if rule['filterType'] == 'PERCENT_PRICE_BY_SIDE':
        prefix='bid' if side=='BUY' else 'ask'
        lo,hi=decimal(rule[prefix+'MultiplierDown']),decimal(rule[prefix+'MultiplierUp'])
    elif rule['filterType']=='PERCENT_PRICE':
        lo,hi=decimal(rule['multiplierDown']),decimal(rule['multiplierUp'])
    else:
        raise ValueError('Percent-price filter required')
    if not 0 < lo <= hi:
        raise ValueError('Invalid multiplier interval')
    return [] if value*lo <= p <= value*hi else ['PERCENT_PRICE_VIOLATION']
