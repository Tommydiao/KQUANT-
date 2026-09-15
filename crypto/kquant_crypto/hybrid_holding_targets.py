"""Conditional A-policy holding targets, not new fills or executable decisions."""
import math


def holding_target(trade, closed_bar, next_bar, *, cutoff):
    as_of = closed_bar.start + 300
    if not (trade['entry_time'] + 300 <= as_of < trade['exit_time']):
        raise ValueError('Snapshot outside observable open holding interval')
    risk = trade['unit_net_risk']
    if not math.isfinite(risk) or risk <= 0:
        raise ValueError('Invalid frozen BASE risk')
    row = {
        'trade_id': trade['trade_id'], 'as_of': as_of,
        'selection': 'ORIGINAL_A_FILLED_HOLDING_TIMES',
        'dependence_group': trade['trade_id'],
        'label_version': 'a_holding_continue_vs_next_open_dev_v1',
        'execution_policy': 'LEGACY_BAR_PROXY_BASE_10_5',
        'counterfactual_comparison': True, 'new_trade': False,
        'holding_features': {
            'age_seconds': as_of-trade['entry_time'],
            'mark_to_entry_r': (closed_bar.close-trade['entry_price'])/risk,
            'base_unit_net_risk': risk},
        'label_available_at': None, 'continue_minus_exit_r': None,
        'label_status': 'UNAVAILABLE',
    }
    if trade['exit_time'] > cutoff:
        row.update(label_status='CENSORED', reason='AUTHORIZED_HISTORY_END')
        return row
    if next_bar is None or next_bar.start != as_of:
        row['reason'] = 'NEXT_BAR_GAP'
        return row
    fee, slip = .001, .0005
    # Entry fees and quantity cancel in this paired comparison. Both alternatives
    # retain the exact original signal-time risk denominator, never mark-time risk.
    exit_now = next_bar.open * (1-slip)
    row.update(label_status='MATURE', reason=trade['exit_reason'],
               label_available_at=trade['exit_time'],
               continue_minus_exit_r=(trade['exit_price']-exit_now)*(1-fee)/risk,
               alternative_exit_price=exit_now,
               alternative_fill_at=as_of,
               actual_policy_exit_at=trade['exit_time'])
    return row
