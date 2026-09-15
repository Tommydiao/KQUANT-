"""Read-only inventory of raw Spot exchangeInfo; never converts it to admission."""
from copy import deepcopy
from .hybrid_mock_broker import decimal, identity, exact_decimal
from .hybrid_order_count_audit import audit_order_count
from .hybrid_reference_price_audit import audit_percent_price

FIELDS = {
    'PRICE_FILTER': ('minPrice','maxPrice','tickSize'),
    'LOT_SIZE': ('minQty','maxQty','stepSize'),
    'MIN_NOTIONAL': ('minNotional',),
    'NOTIONAL': ('minNotional','maxNotional'),
}


def audit_symbol(payload, symbol):
    rows = [r for r in payload.get('symbols', []) if r.get('symbol') == symbol]
    if len(rows) != 1:
        raise ValueError('Exactly one symbol record required')
    row = rows[0]
    filters = {}
    for item in row.get('filters', []):
        name = item.get('filterType')
        if not isinstance(name, str) or not name or name in filters:
            raise ValueError('Duplicate or invalid filter identity')
        filters[name] = deepcopy(item)
    blockers = []
    for required in ('PRICE_FILTER', 'LOT_SIZE'):
        if required not in filters:
            blockers.append('MISSING:' + required)
    if not {'NOTIONAL','MIN_NOTIONAL'} & filters.keys():
        blockers.append('MISSING:NOTIONAL_BOUND')
    for name, item in filters.items():
        if name not in FIELDS:
            blockers.append('REQUIRES_CONTEXT_OR_IMPLEMENTATION:' + name)
            continue
        for field in FIELDS[name]:
            if field not in item:
                blockers.append('MISSING:' + name + '.' + field)
            else:
                decimal(item[field])
    if row.get('status') != 'TRADING':
        blockers.append('SYMBOL_NOT_TRADING')
    if row.get('isSpotTradingAllowed') is not True:
        blockers.append('SPOT_PERMISSION_UNCONFIRMED')
    return {'symbol': symbol, 'raw_filters': filters, 'snapshot_hash': identity('raw_rules', row),
            'blockers': blockers, 'scope': 'RAW_RULE_INVENTORY_NOT_VALIDATION',
            'execution_allowed': False, 'account_constraints_verified': False}


@exact_decimal
def audit_limit_ioc(payload, symbol, *, price, quantity, order_count=None, now=None, max_count_age=None,
                    side='BUY', reference=None, max_reference_age=None):
    if side not in ('BUY','SELL'):
        raise ValueError('Explicit valid order side required')
    inventory = audit_symbol(payload, symbol)
    target = next(r for r in payload['symbols'] if r.get('symbol') == symbol)
    p, q = decimal(price), decimal(quantity)
    if p <= 0 or q <= 0:
        raise ValueError('Positive price and quantity required')
    blockers = [r for r in inventory['blockers'] if not r.startswith('REQUIRES_CONTEXT_OR_IMPLEMENTATION:')]
    if 'LIMIT' not in target.get('orderTypes', []):
        blockers.append('LIMIT_ORDER_SUPPORT_UNCONFIRMED')
    exchange_filters = payload.get('exchangeFilters')
    if not isinstance(exchange_filters, list):
        blockers.append('EXCHANGE_FILTERS_UNCONFIRMED')
        exchange_filters = []
    seen = set()
    for rule in exchange_filters:
        name = rule.get('filterType')
        if not isinstance(name, str) or not name or name in seen:
            raise ValueError('Invalid or duplicate exchange filter')
        seen.add(name)
        blockers.append('EXCHANGE_CONTEXT_REQUIRED:' + name)
    not_applicable = []
    for name, f in inventory['raw_filters'].items():
        if name == 'PRICE_FILTER' and all(k in f for k in FIELDS[name]):
            low, high, tick = (decimal(f[k]) for k in FIELDS[name])
            if (low and p < low) or (high and p > high) or (tick and p % tick):
                blockers.append('PRICE_FILTER_VIOLATION')
        elif name == 'LOT_SIZE' and all(k in f for k in FIELDS[name]):
            low, high, step = (decimal(f[k]) for k in FIELDS[name])
            if step <= 0 or not low <= q <= high or q % step:
                blockers.append('LOT_SIZE_VIOLATION')
        elif name in ('NOTIONAL','MIN_NOTIONAL') and all(k in f for k in FIELDS[name]):
            if p*q < decimal(f['minNotional']) or (name == 'NOTIONAL' and p*q > decimal(f['maxNotional'])):
                blockers.append('NOTIONAL_VIOLATION:' + name)
        elif name in ('MARKET_LOT_SIZE','ICEBERG_PARTS','TRAILING_DELTA','MAX_NUM_ICEBERG_ORDERS',
                      'MAX_NUM_ALGO_ORDERS','MAX_NUM_ORDER_LISTS','MAX_NUM_ORDER_AMENDS'):
            not_applicable.append(name)
        elif name == 'MAX_NUM_ORDERS' and now is not None and max_count_age is not None:
            counts = audit_order_count(symbol=symbol, limit=f.get('maxNumOrders'),
                                       snapshot=order_count, now=now, max_age=max_count_age)
            blockers.extend(counts['blockers'])
        elif name in ('PERCENT_PRICE','PERCENT_PRICE_BY_SIDE') and now is not None and max_reference_age is not None:
            blockers.extend(audit_percent_price(f,symbol=symbol,side=side,price=price,
                            reference=reference,now=now,max_age=max_reference_age))
        elif name not in FIELDS:
            blockers.append('CONTEXT_OR_IMPLEMENTATION_REQUIRED:' + name)
    return {'scope':'PLAIN_LIMIT_IOC_PREFLIGHT_ONLY',
            'order_contract':'NEW_STANDALONE_LIMIT_IOC_NO_ICEBERG_NO_TRAILING_NO_AMENDMENT',
            'protection_order_validation_included':False,
            'snapshot_hash':identity('ioc_rules', {'symbol':target,'exchangeFilters':payload.get('exchangeFilters')}),
            'blockers':blockers, 'not_applicable':not_applicable, 'execution_allowed':False,
            'raw_exchange_filters':deepcopy(exchange_filters),
            'account_constraints_verified':False, 'quantity_adjusted':False}
