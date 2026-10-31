from datetime import UTC, datetime, timedelta

import pytest

from kquant.options_one_minute_manual import _reference_loss_reasons
from kquant.options_one_minute_manual import exit_reasons
from kquant import options_opening_momentum as momentum


@pytest.mark.parametrize('fees', [None, 1])
@pytest.mark.parametrize('quote_state', ['missing', 'stale'])
def test_missing_or_stale_quote_is_independent_of_fee_availability(fees, quote_state):
    now = datetime(2026, 10, 9, 15, tzinfo=UTC)
    position = dict(contract_id='TEST_ONLY', multiplier=100, entry_fees=fees,
                    exit_fee_estimate=fees, quantity=2, open_quantity=1, entry_price=1)
    quote = None if quote_state == 'missing' else dict(contract_id='TEST_ONLY',
        multiplier=100, depth_status='available', bid=.5,
        bbo_received_at=(now - timedelta(seconds=4)).isoformat())
    reasons = _reference_loss_reasons(position, quote, now, {'premium_loss_review_fraction': .2})
    codes = {row['reason'] for row in reasons}
    assert 'OPTION_QUOTE_STALE_EXIT_UNVERIFIED' in codes
    assert 'NET_REFERENCE_PREMIUM_LOSS_REVIEW' not in codes
    assert ('REFERENCE_LOSS_FEES_UNKNOWN' in codes) == (fees is None)
    assert position['open_quantity'] == 1


@pytest.mark.parametrize('fees', [None, 0])
def test_fresh_zero_bid_is_valid_but_unknown_fees_prevent_loss_estimate(fees):
    now = datetime(2026, 10, 9, 15, tzinfo=UTC)
    position = dict(contract_id='TEST_ONLY', multiplier=100, entry_fees=fees,
                    exit_fee_estimate=fees, quantity=2, open_quantity=1, entry_price=1)
    quote = dict(contract_id='TEST_ONLY', multiplier=100, depth_status='available',
                 bid=0, bbo_received_at=now.isoformat())
    reasons = _reference_loss_reasons(position, quote, now, {'premium_loss_review_fraction': .2})
    codes = {row['reason'] for row in reasons}
    assert 'OPTION_QUOTE_STALE_EXIT_UNVERIFIED' not in codes
    assert ('NET_REFERENCE_PREMIUM_LOSS_REVIEW' in codes) == (fees is not None)
    assert position['open_quantity'] == 1


def reported_position():
    policy = momentum.load_policy()
    return dict(strategy_id=policy['policy_id'], strategy_hash=policy['policy_hash'],
        policy_snapshot=policy, symbol='TEST', right='CALL', contract_id='TEST_ONLY',
        multiplier=100, entry_fees=0, exit_fee_estimate=0, quantity=2, open_quantity=1,
        entry_price=1, underlying_entry_price=105, trigger_low=100, trigger_high=106,
        reported_execution_at='2026-10-09T13:35:00+00:00')


def test_public_momentum_exit_path_keeps_independent_warnings_and_never_closes():
    position = reported_position()
    codes = {row['reason'] for row in exit_reasons(position, [],
        now=datetime(2026, 10, 9, 14, tzinfo=UTC))}
    assert {'OPTION_QUOTE_STALE_EXIT_UNVERIFIED', 'UNDERLYING_BAR_STALE_EXIT_UNVERIFIED',
            'UNDERLYING_QUOTE_STALE_TOUCH_UNVERIFIED'} <= codes
    assert position['open_quantity'] == 1
    position['open_quantity'] = 0
    assert exit_reasons(position, [], now=datetime(2026, 10, 9, 14, tzinfo=UTC)) == []


def test_bedtime_and_overnight_warnings_do_not_infer_exit():
    position = reported_position()
    # 17:30 UTC is 01:30 Beijing and earlier than four hours from this entry.
    codes = {row['reason'] for row in exit_reasons(position, [],
        now=datetime(2026, 10, 9, 17, 30, tzinfo=UTC))}
    assert {'BEDTIME_WIND_DOWN_REVIEW', 'MAX_HOLD_OR_BEDTIME_EXIT'} <= codes
    codes = {row['reason'] for row in exit_reasons(position, [],
        now=datetime(2026, 10, 10, 14, tzinfo=UTC))}
    assert 'UNCONFIRMED_OVERNIGHT_POSITION' in codes
    assert position['open_quantity'] == 1
