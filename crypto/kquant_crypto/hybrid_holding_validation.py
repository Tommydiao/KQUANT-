"""Retrospective information-interval audit, never a fitted validation policy."""
import math


def audit_intervals(trades, boundaries):
    """All assets share calendar boundaries; label endpoints include exit bar.

    The original OHLC simulator timestamps an intrabar exit at bar start.
    Its outcome cannot be known until that bar closes. Using exit_time alone
    would understate information overlap by up to five minutes.
    """
    rows = []
    identities = set()
    for trade in trades:
        identity = trade['trade_id']
        if identity in identities:
            raise ValueError('Duplicate trade identity')
        identities.add(identity)
        start, entry, exit_ = (trade[k] for k in ('signal_time', 'entry_time', 'exit_time'))
        if any(type(t) is not int or t < 0 for t in (start, entry, exit_)) or not start <= entry <= exit_:
            raise ValueError('Invalid information or holding interval')
        # Conservative for all OHLC exits, including opening exits. This does
        # not replace original trade timestamps or claim measured availability.
        end = exit_ + 300
        rows.append({'trade_id': identity, 'symbol': trade['symbol'], 'mode': trade['mode'],
                     'information_start': start, 'information_end': end,
                     'holding_seconds': exit_ - entry,
                     'availability_basis': 'conservative_exit_bar_close_proxy'})
    rows.sort(key=lambda r: (r['information_start'], r['trade_id']))
    groups = []
    for row in rows:
        if not groups or row['information_start'] > groups[-1]['end']:
            groups.append({'start': row['information_start'], 'end': row['information_end'], 'trade_ids': []})
        groups[-1]['end'] = max(groups[-1]['end'], row['information_end'])
        groups[-1]['trade_ids'].append(row['trade_id'])
        row['dependency_group'] = len(groups) - 1
    if any(type(b) is not int or b % 86400 for b in boundaries) or boundaries != sorted(set(boundaries)):
        raise ValueError('Unique ordered UTC date boundaries required')
    cuts = []
    for boundary in boundaries:
        previous = [r for r in rows if r['information_start'] < boundary]
        purged = [r for r in previous if r['information_end'] >= boundary]
        cuts.append({'boundary': boundary, 'prior_signals': len(previous),
                     'interval_purged': len(purged), 'interval_purged_ids': [r['trade_id'] for r in purged],
                     'prior_labels_available': len(previous) - len(purged),
                     'crossing_despite_signal_6h_before_boundary': sum(
                         r['information_start'] < boundary - 21600 for r in purged)})
    return {'rows': rows, 'dependency_groups': groups, 'cuts': cuts,
            'max_holding_hours': max((r['holding_seconds'] / 3600 for r in rows), default=None),
            'holds_over_6h': sum(r['holding_seconds'] > 21600 for r in rows),
            'embargo_policy_status': 'UNFROZEN_FOR_NEW_HOLDING_TARGET',
            'independent_oos': False, 'future_fit_authorized': False}


def capital_time(trades):
    hours = 0.0
    pnl = 0.0
    for trade in trades:
        amount = trade['quantity'] * trade['entry_price'] + trade['entry_fee']
        duration = (trade['exit_time'] - trade['entry_time']) / 3600
        if not math.isfinite(amount) or amount <= 0 or duration < 0:
            raise ValueError('Invalid invested capital or duration')
        hours += amount * duration
        pnl += trade['net_pnl']
    return {'capital_hours': hours, 'net_pnl_per_capital_hour': pnl / hours if hours else None,
            'definition': 'sum actual paid entry capital including fee times holding hours; not annualized return'}
