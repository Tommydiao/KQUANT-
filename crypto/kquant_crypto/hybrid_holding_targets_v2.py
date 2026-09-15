"""Versioned conditional holding labels, not extra trades or model inputs."""
import math


def holding_target_v2(trade, closed_bar, next_bar, *, cutoff, policy, path_complete):
    if policy not in {'ORIGINAL', 'FIXED_2_5R', 'FIXED_3R', 'T1', 'T2'}:
        raise ValueError('Unregistered holding policy')
    as_of = closed_bar.start + 300
    if not trade['entry_time'] + 300 <= as_of < trade['exit_time']:
        raise ValueError('Snapshot not within an observable open position')
    risk = trade['base_unit_net_risk']
    values = [risk, trade['entry_price'], trade['exit_price'], closed_bar.close,
              trade['quantity'], trade['entry_fee'], trade['fees']]
    if not all(math.isfinite(v) for v in values) or risk <= 0 or trade['quantity'] <= 0:
        raise ValueError('Invalid frozen risk or cashflows')
    if trade['cost_multiplier'] != 1 or trade['fee_bps'] != 10 or trade['execution_source'] != 'ohlcv':
        raise ValueError('Only frozen BASE OHLCV contract supported')
    known_at = trade['exit_time'] + 300
    row = {'trade_id': trade['trade_id'], 'policy': policy, 'as_of': as_of,
        'available_at': as_of, 'availability_basis': 'assumed_closed_5m_historical_proxy',
        'label_version': 'holding_policy_continue_vs_next_open_dev_v2',
        'selection': 'ACTUAL_FILLED_HOLDINGS_WITHIN_EACH_FROZEN_POLICY',
        'dependence_group': trade['trade_id'], 'counterfactual_comparison': True,
        'new_trade': False, 'fill_status': 'FILLED_SOURCE_TRADE',
        'execution_quality': 'LEGACY_BAR_PROXY', 'scope': 'DEV_ONLY',
        'runtime_enabled': False, 'independent_oos': False,
        'label_available_at': None, 'continue_minus_exit_r': None,
        'label_status': 'UNAVAILABLE', 'holding_features': {
            'age_seconds': as_of - trade['entry_time'],
            'mark_to_entry_r': (closed_bar.close - trade['entry_price']) / risk,
            'base_unit_net_risk': risk}}
    if known_at > cutoff:
        return dict(row, label_status='CENSORED', reason='EXIT_BAR_NOT_YET_CLOSED_AT_AUTHORIZED_END')
    if not path_complete or trade.get('path_unverifiable', True):
        return dict(row, reason='HOLDING_PATH_GAP_OR_UNVERIFIABLE')
    if next_bar is None or next_bar.start != as_of or not math.isfinite(next_bar.open) or next_bar.open <= 0:
        return dict(row, reason='NEXT_BAR_GAP_OR_INVALID')
    actual_exit_fee = trade['fees'] - trade['entry_fee']
    expected_fee = trade['quantity'] * trade['exit_price'] * .001
    if not math.isclose(actual_exit_fee, expected_fee, abs_tol=1e-8, rel_tol=1e-8):
        raise ValueError('Source fee contract differs from BASE')
    alternative = next_bar.open * .9995
    # Entry fees cancel; realized exit costs are taken from the source ledger.
    actual_net = trade['exit_price'] - actual_exit_fee / trade['quantity']
    alternative_net = alternative * .999
    return dict(row, label_status='MATURE', reason=trade['exit_reason'],
        label_available_at=known_at, actual_policy_exit_at=trade['exit_time'],
        alternative_fill_at=as_of, alternative_exit_price=alternative,
        continue_minus_exit_r=(actual_net - alternative_net) / risk,
        outcome_kind='TERMINAL_LIQUIDATION' if 'terminal' in trade['exit_reason'] else 'POLICY_EXIT',
        execution_policy_id=trade['policy_hash'])
