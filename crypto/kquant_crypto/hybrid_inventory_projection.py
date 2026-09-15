"""Synthetic fill-derived inventory projection, never an account balance or order."""
from dataclasses import asdict
from decimal import Decimal, ROUND_DOWN

from .hybrid_mock_broker import decimal, exact_decimal
from .hybrid_spot_stream_contract_v12 import FillFact


@exact_decimal
def project_inventory(fills, *, symbol, base_asset, quote_asset, opening_base,
                      locked_base, step_size, min_quantity, min_notional, bid):
    if not all(isinstance(x, str) and x.strip() for x in (symbol, base_asset, quote_asset)) or base_asset == quote_asset:
        raise ValueError('Explicit instrument and distinct assets required')
    balance, locked = decimal(opening_base), decimal(locked_base)
    step, minimum, notional, price = map(decimal, (step_size, min_quantity, min_notional, bid))
    if step <= 0 or price <= 0:
        raise ValueError('Positive current step and bid required')
    seen, fees, blockers = {}, {}, set()
    for fill in fills:
        if not isinstance(fill, FillFact) or fill.symbol != symbol or fill.side not in ('BUY', 'SELL'):
            raise ValueError('Matching normalized fill facts required')
        if not fill.fill_key:
            raise ValueError('Stable fill identity required')
        fact = asdict(fill)
        if fill.fill_key in seen:
            if seen[fill.fill_key] != fact:
                raise ValueError('Conflicting duplicate fill')
            continue
        seen[fill.fill_key] = fact
        quantity = decimal(fill.quantity)
        if quantity <= 0:
            raise ValueError('Positive fill quantity required')
        balance += quantity if fill.side == 'BUY' else -quantity
        if fill.commission is None:
            blockers.add('COMMISSION_UNKNOWN')
            continue
        fee = decimal(fill.commission)
        if fee and not fill.commission_asset:
            blockers.add('COMMISSION_ASSET_UNKNOWN')
        elif fee:
            fees[fill.commission_asset] = fees.get(fill.commission_asset, Decimal(0)) + fee
            if fill.commission_asset == base_asset:
                balance -= fee
    if balance < 0:
        blockers.add('NEGATIVE_INVENTORY_REQUIRES_RECONCILIATION')
    if locked > balance:
        blockers.add('LOCKED_EXCEEDS_PROJECTED_BALANCE')
    free = balance - locked
    rounded = (max(Decimal(0), free) / step).to_integral_value(rounding=ROUND_DOWN) * step
    eligible = not blockers and rounded > 0 and rounded >= minimum and rounded * price >= notional
    return {
        'scope': 'SYNTHETIC_FILL_INVENTORY_PROJECTION', 'symbol': symbol,
        'projected_base': str(balance), 'locked_base': str(locked), 'free_base': str(free),
        'rounded_quantity': str(rounded) if not blockers else None,
        'step_remainder': str(free - rounded) if not blockers else None,
        'below_minimum_unsellable': str(max(Decimal(0), free)) if not blockers and not eligible else None,
        'native_commissions': {asset: str(value) for asset, value in sorted(fees.items())},
        'blockers': sorted(blockers), 'unique_fills': len(seen),
        'minimum_filters_satisfied': eligible, 'account_reconciled': False,
        'execution_allowed': False,
        'limitation': 'No deposits, withdrawals or manual changes inferred; filters and bid freshness require separate validation',
    }
