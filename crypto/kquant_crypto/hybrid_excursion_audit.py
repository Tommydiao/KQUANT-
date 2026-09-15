"""Post-hoc bounded OHLC excursions, never eligible as decision features."""
import math


def audit_excursion(trade, bars, cutoff):
    entry, end = trade['entry_time'], trade['exit_time']
    if end > cutoff or entry > end or trade['execution_source'] != 'ohlcv':
        raise ValueError('Authorized historical proxy interval required')
    if trade.get('path_unverifiable'):
        return dict(status='UNAVAILABLE',reason='PATH_UNVERIFIABLE')
    risk = trade['base_unit_net_risk']
    if risk <= 0 or trade['quantity'] <= 0:
        raise ValueError('Positive frozen risk and quantity required')
    full = [b for b in bars if entry <= b.start and b.start+300 <= end]
    expected = list(range(entry, end, 300))
    expected = [start for start in expected if start+300 <= end]
    if [b.start for b in full] != expected:
        return dict(status='UNAVAILABLE',reason='HOLDING_GAP')
    # Intrabar protection timestamps are recorded at bar close; the remainder
    # of that OHLC bar may occur after exit, so its extrema are not admissible.
    uncertain_exit = trade['exit_reason'] in ('stop','target')
    observed = [b for b in full if not (uncertain_exit and b.start+300 == end)]
    paid = trade['entry_price'] + trade['entry_fee']/trade['quantity']
    fee = trade['fee_bps']/10000
    slip = trade['execution_cost_bps']/10000
    mark = lambda price: (price*(1-slip)*(1-fee)-paid)/risk
    if not all(math.isfinite(mark(value)) for b in observed for value in (b.high,b.low)):
        raise ValueError('Invalid excursion values')
    high = max(observed,key=lambda b:b.high) if observed else None
    low = min(observed,key=lambda b:b.low) if observed else None
    retained_target = trade.get('target')
    structural = trade.get('strategy_version','').split(':')[-1] in ('T1','T2') and trade.get('mode') == 'UP_TREND'
    target = None if structural else retained_target
    touched = next((b for b in observed if target is not None and b.high >= target),None)
    return dict(status='AVAILABLE',posthoc_only=True,feature_eligible=False,
        complete_pre_exit_bars=len(observed),exit_bar_extrema_excluded=uncertain_exit,
        net_mfe_observed=mark(high.high) if high else None,
        net_mae_observed=mark(low.low) if low else None,
        mfe_first_interval=[high.start,high.start+300] if high else None,
        mae_first_interval=[low.start,low.start+300] if low else None,
        target_reference=target,
        retained_original_target_not_active=retained_target if structural else None,
        target_touch_before_exit_interval=[touched.start,touched.start+300] if touched else None,
        target_exit_recorded=trade['exit_reason'] in ('target','gap_target'),
        target_touch_status='NO_FIXED_TARGET' if target is None else 'PRE_EXIT_TOUCH' if touched else
            'RECORDED_TARGET_EXIT' if trade['exit_reason'] in ('target','gap_target') else
            'EXIT_BAR_ORDER_UNRESOLVED' if uncertain_exit else 'NOT_OBSERVED_BEFORE_EXIT',
        exact_intrabar_time_known=False,full_lifecycle_extrema_proven=not uncertain_exit,
        net_r=trade['net_r'],base_unit_net_risk=risk)
