"""Ordered bar execution primitive for research replay and path simulation."""


def exit_on_bar(bar, stop, target=None, pending_reason=None):
    if bar.open <= stop:
        return bar.open, bar.start, 'gap_stop'
    if target is not None and bar.open >= target:
        return target, bar.start, 'gap_target'
    if pending_reason:
        return bar.open, bar.start, pending_reason
    if bar.low <= stop:
        return stop, bar.start+300, 'stop'
    if target is not None and bar.high >= target:
        return target, bar.start+300, 'target'
    return None


def realized_net_r(entry_price, exit_reference, base_risk, cost_multiplier=1):
    if base_risk<=0 or cost_multiplier not in (1,2):
        raise ValueError('Invalid frozen risk or cost scenario')
    fee, slip = .001*cost_multiplier,.0005*cost_multiplier
    exit_price = exit_reference*(1-slip)
    return (exit_price-entry_price-fee*(entry_price+exit_price))/base_risk
