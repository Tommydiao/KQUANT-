"""Descriptive opportunity and cash-cost bridges; no strategy decisions."""
from collections import Counter
import math


def opportunity_key(trade):
    return (trade['symbol'], trade['mode'], trade['signal_time'])


def cost_bridge(trade):
    fields = ('quantity', 'entry_market_reference', 'exit_market_reference',
              'entry_price', 'exit_price', 'fees', 'net_pnl', 'base_unit_net_risk')
    if any(not math.isfinite(float(trade[k])) for k in fields):
        raise ValueError('Nonfinite trade evidence')
    q = trade['quantity']
    if q <= 0 or trade['base_unit_net_risk'] <= 0:
        raise ValueError('Positive quantity and BASE risk required')
    gross = q * (trade['exit_market_reference'] - trade['entry_market_reference'])
    entry_slip = q * (trade['entry_price'] - trade['entry_market_reference'])
    exit_slip = q * (trade['exit_market_reference'] - trade['exit_price'])
    reconstructed = gross - entry_slip - exit_slip - trade['fees']
    if not math.isclose(reconstructed, trade['net_pnl'], abs_tol=1e-7):
        raise ValueError('Cash bridge does not reconcile')
    denominator = q * trade['base_unit_net_risk']
    return dict(gross_reference_pnl=gross, entry_slippage=entry_slip,
                exit_slippage=exit_slip, fees=trade['fees'], net_pnl=reconstructed,
                base_risk_cash=denominator, net_base_r=reconstructed/denominator,
                cost_to_base_risk=(entry_slip+exit_slip+trade['fees'])/denominator)


def compare_opportunities(base, challenger):
    def indexed(rows):
        result = {opportunity_key(row): row for row in rows}
        if len(result) != len(rows):
            raise ValueError('Duplicate economic opportunity in one policy')
        return result
    a, b = indexed(base), indexed(challenger)
    common = sorted(a.keys() & b.keys())
    return dict(common=common, baseline_only=sorted(a.keys()-b.keys()),
                challenger_only=sorted(b.keys()-a.keys()),
                common_cash_delta=sum(b[k]['net_pnl']-a[k]['net_pnl'] for k in common),
                baseline_only_cash=sum(a[k]['net_pnl'] for k in a.keys()-b.keys()),
                challenger_only_cash=sum(b[k]['net_pnl'] for k in b.keys()-a.keys()),
                interpretation='Descriptive portfolio composition; common cash delta also includes sizing, not pure exit effect')


def summarize_bridge(rows):
    bridges = [cost_bridge(row) for row in rows]
    keys = ('gross_reference_pnl', 'entry_slippage', 'exit_slippage', 'fees', 'net_pnl')
    return dict(trades=len(rows), **{key: sum(row[key] for row in bridges) for key in keys},
                exits=dict(Counter(row['exit_reason'] for row in rows)))


def classify_opportunity(opportunity, label, events, trades):
    key = opportunity_key(opportunity)
    matching = [t for t in trades if opportunity_key(t) == key]
    relevant = [e for e in events if e['symbol'] == key[0] and e['time'] == key[2]
                and e['kind'] in ('SIGNAL_RESERVED', 'ENTRY_REJECTED')]
    if len(matching) > 1 or len(relevant) != 1:
        raise ValueError('Opportunity decision is missing or ambiguous')
    event = relevant[0]
    filled = bool(matching)
    if filled and event['kind'] != 'SIGNAL_RESERVED':
        raise ValueError('Fill without admission')
    if not filled and event['kind'] == 'SIGNAL_RESERVED':
        # A reservation is not proof of fill or a mature outcome.
        return dict(fill_status='RESERVED_UNRESOLVED', label_status='PENDING_AUDIT', net_r=None,
                    reason='reservation_without_completed_trade', decision_event_id=event['event_id'])
    if filled:
        trade = matching[0]
        return dict(fill_status='FILLED_VIRTUAL', label_status='UNAVAILABLE' if trade.get('path_unverifiable') else 'MATURE',
                    net_r=None if trade.get('path_unverifiable') else trade['net_r'], reason=trade['exit_reason'],
                    decision_event_id=event['event_id'],trade_id=trade['trade_id'])
    if label is not None and label.get('net_r') is not None:
        raise ValueError('Unfilled opportunity cannot carry a baseline trade return')
    return dict(fill_status='NOT_FILLED',label_status='NOT_APPLICABLE_NO_TRADE',net_r=None,
                reason=event.get('reason','unknown'),decision_event_id=event['event_id'])


def rejection_occupancy(events):
    """Audit the persisted event order, never reconstruct unavailable prices."""
    pending, positions, rejected = {}, {}, []
    previous_id = -1
    pause_until = 0
    daily_pause_day = None
    for event in events:
        identity = int(event['event_id'])
        if identity <= previous_id:
            raise ValueError('Event order or identity conflict')
        previous_id = identity
        kind, symbol, now = event['kind'], event['symbol'], event['time']
        if kind == 'SIGNAL_RESERVED':
            if symbol in pending or symbol in positions:
                raise ValueError('Duplicate active symbol')
            pending[symbol] = dict(trade_id=event['plan']['trade_id'], since=now,
                                   admission_event_id=event['event_id'])
        elif kind == 'VIRTUAL_ENTRY':
            if symbol not in pending or pending[symbol]['trade_id'] != event['trade_id']:
                raise ValueError('Entry has no matching reservation')
            positions[symbol] = dict(pending.pop(symbol), entered_at=now)
        elif kind == 'VIRTUAL_EXIT':
            if symbol not in positions or positions[symbol]['trade_id'] != event['trade_id']:
                raise ValueError('Exit has no matching position')
            positions.pop(symbol)
        elif kind == 'ENTRY_CANCELED':
            if symbol not in pending:
                raise ValueError('Cancellation has no reservation')
            pending.pop(symbol)
        elif kind == 'LOSS_STREAK_PAUSE':
            pause_until = event['until']
        elif kind == 'DAILY_LOSS_PAUSE':
            daily_pause_day = int(now)//86400
        elif kind == 'ENTRY_REJECTED':
            reason = event['reason']
            own = pending.get(symbol) or positions.get(symbol)
            supported = (bool(own) if reason == 'already_exposed' else
                         (now < pause_until or int(now)//86400 == daily_pause_day) if reason == 'risk_pause' else None)
            if supported is False:
                raise ValueError('Rejection contradicted by prior events')
            rejected.append(dict(symbol=symbol, signal_time=now, event_id=event['event_id'],
                reason=reason, prior_event_support=supported,
                blocking_same_symbol=own, pending=dict(pending), positions=dict(positions),
                pause_until=pause_until, daily_pause_day=daily_pause_day))
    return dict(rejections=rejected, remaining_pending=pending, remaining_positions=positions)
