"""Post-hoc close-observed exit quality. Never a model feature or signal."""
import math


def exit_quality(trade, bars, cutoff):
    entry, exit_ = trade['entry_time'], trade['exit_time']
    if entry > exit_ or exit_ > cutoff or trade['execution_source'] != 'ohlcv':
        raise ValueError('Authorized OHLC trade required')
    if trade.get('path_unverifiable'):
        return {'status': 'UNAVAILABLE', 'reason': 'PATH_UNVERIFIABLE'}
    risk, qty = trade['base_unit_net_risk'], trade['quantity']
    fee, slip = trade['fee_bps']/10000, trade['execution_cost_bps']/10000
    if min(risk, qty) <= 0 or not 0 <= fee < 1 or not 0 <= slip < 1:
        raise ValueError('Known positive BASE risk and actual cost schedule required')
    # A bar whose close occurs after the exit cannot contribute a pre-exit peak.
    observed = [b for b in bars if entry <= b.start and b.start + 300 <= exit_]
    expected = list(range(entry, exit_, 300))
    expected = [t for t in expected if t + 300 <= exit_]
    if [b.start for b in observed] != expected:
        return {'status': 'UNAVAILABLE', 'reason': 'HOLDING_CLOSE_GAP'}
    paid = trade['entry_price'] + trade['entry_fee']/qty
    marks = [(b.close*(1-slip)*(1-fee)-paid)/risk for b in observed]
    if not all(math.isfinite(r) for r in marks + [trade['net_r']]):
        raise ValueError('Nonfinite net outcome')
    peak = max([0.0, trade['net_r']] + marks)
    return {'status': 'AVAILABLE', 'reason': None, 'closed_marks': len(observed),
            'observed_peak_net_r': peak, 'net_r': trade['net_r'],
            'giveback_net_r': peak-trade['net_r'],
            'capture_of_observed_peak': trade['net_r']/peak if peak > 0 else None,
            'holding_hours': (exit_-entry)/3600, 'base_unit_net_risk': risk,
            'basis': 'closed 5m liquidation marks plus realized exit; excludes intrabar highs and exit-bar future',
            'true_intrabar_mfe_verified': False, 'posthoc_only': True, 'feature_eligible': False}
