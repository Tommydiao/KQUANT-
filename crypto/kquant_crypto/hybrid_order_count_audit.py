"""Evaluate explicit count snapshots without accessing or approving an account."""


def audit_order_count(*, symbol, limit, snapshot, now, max_age):
    if type(limit) is not int or limit < 1 or type(now) is not int or now < 0 or type(max_age) is not int or max_age < 0:
        raise ValueError('Explicit integer count policy required')
    reasons = []
    if snapshot is None:
        reasons.append('ORDER_COUNT_UNAVAILABLE')
    elif not isinstance(snapshot, dict):
        raise ValueError('Explicit snapshot required')
    else:
        if snapshot.get('symbol') != symbol:
            reasons.append('ORDER_COUNT_SYMBOL_MISMATCH')
        at = snapshot.get('available_at')
        if type(at) is not int or at < 0 or not 0 <= now-at <= max_age:
            reasons.append('ORDER_COUNT_STALE_OR_FUTURE')
        count = snapshot.get('open_orders')
        pending = snapshot.get('reserved_new_orders')
        if any(type(v) is not int or v < 0 for v in (count, pending)):
            reasons.append('ORDER_COUNT_INCOMPLETE')
        elif count + pending + 1 > limit:
            reasons.append('ORDER_COUNT_LIMIT_EXCEEDED')
        if snapshot.get('includes_algo_orders') is not True:
            reasons.append('ALGO_ORDER_COUNT_UNCONFIRMED')
        if snapshot.get('reconciled') is not True:
            reasons.append('ORDER_COUNT_NOT_RECONCILED')
    return {'blockers': reasons, 'scope': 'INPUT_CONTRACT_ONLY',
            'account_verified': False, 'execution_allowed': False}
