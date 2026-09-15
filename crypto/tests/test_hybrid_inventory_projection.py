from dataclasses import replace
from decimal import Decimal, localcontext

import pytest

from kquant_crypto.hybrid_inventory_projection import project_inventory
from kquant_crypto.hybrid_spot_stream_contract_v12 import FillFact


def fill(**changes):
    value = FillFact('f1', 'o1', 'BTCUSDT', 1, 1, 'BUY', Decimal('1'),
                     Decimal('100'), Decimal('100'), Decimal('.001'), 'BTC', 1000)
    return replace(value, **changes)


def project(fills, **changes):
    args = dict(symbol='BTCUSDT', base_asset='BTC', quote_asset='USDT',
                opening_base='0', locked_base='0', step_size='.01', min_quantity='.01',
                min_notional='5', bid='100')
    return project_inventory(fills, **(args | changes))


def test_base_fee_and_dust_preserved_with_duplicates():
    result = project([fill(), fill()])
    assert result['projected_base'] == '0.999'
    assert result['rounded_quantity'] == '0.99'
    assert result['step_remainder'] == '0.009'
    assert result['unique_fills'] == 1
    assert not result['execution_allowed']


def test_quote_fee_does_not_reduce_base_and_locked_is_not_sellable():
    result = project([fill(commission_asset='USDT')], locked_base='.2')
    assert result['projected_base'] == '1'
    assert Decimal(result['rounded_quantity']) == Decimal('.8')


def test_unknown_fee_abstains_and_negative_inventory_is_not_zeroed():
    assert project([fill(commission=None)])['rounded_quantity'] is None
    result = project([fill(side='SELL')])
    assert Decimal(result['projected_base']) < 0
    assert result['rounded_quantity'] is None


def test_conflict_rejected_and_low_notional_not_rounded_up():
    with pytest.raises(ValueError, match='Conflicting'):
        project([fill(), fill(commission=Decimal('.02'))])
    result = project([fill(quantity=Decimal('.04'), commission=Decimal('0'))])
    assert not result['minimum_filters_satisfied']
    assert Decimal(result['below_minimum_unsellable']) == Decimal('.04')


def test_decimal_context_independence_and_no_cross_symbol_merge():
    expected = project([fill()])
    with localcontext() as ctx:
        ctx.prec = 2
        assert project([fill()]) == expected
    with pytest.raises(ValueError, match='Matching'):
        project([fill(symbol='ETHUSDT')])
