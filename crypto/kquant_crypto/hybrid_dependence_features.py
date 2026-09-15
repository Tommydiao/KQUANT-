"""Closed-hour dependence features for the fixed three-core universe only."""
import math
from .hybrid_multifactor_dev import CORE_SYMBOLS

DEPENDENCE_DEFINITIONS = {
    'corr_btc24': 'Pearson correlation of last24 synchronized hourly log returns with BTC',
    'corr_eth24': 'Pearson correlation of last24 synchronized hourly log returns with ETH',
    'core_mean_pair_corr24': 'mean three off-diagonal pair correlations on synchronized last24 hourly log returns',
    'vol6_to_prior18': 'population_sd(last6 log returns)/population_sd(preceding18 log returns)',
}


def covariance(a, b):
    if not a or len(a) != len(b):
        raise ValueError('Nonempty aligned series required')
    ma, mb = math.fsum(a) / len(a), math.fsum(b) / len(b)
    return math.fsum((x - ma) * (y - mb) for x, y in zip(a, b)) / len(a)


def correlation(a, b):
    va, vb = covariance(a, a), covariance(b, b)
    if va <= 0 or vb <= 0:
        return None
    return min(1.0, max(-1.0, covariance(a, b) / math.sqrt(va * vb)))


def dependence_snapshot(histories, symbol, as_of):
    result = {'version': 'core_dependence_dev_v1', 'as_of': as_of, 'available_at': as_of,
              'availability_basis': 'assumed_close_historical_replay',
              'status': 'MISSING_SYNCHRONIZED_CORE_HISTORY',
              'scope': 'THREE_CORE_ASSETS_NOT_WHOLE_MARKET',
              'universe': list(CORE_SYMBOLS), 'values': {k: None for k in DEPENDENCE_DEFINITIONS},
              'covariance_matrix': None, 'covariance_units': 'hourly_log_return_squared',
              'execution_enabled': False}
    if symbol not in CORE_SYMBOLS or set(histories) != set(CORE_SYMBOLS):
        return result
    returns = {}
    for name in CORE_SYMBOLS:
        bars = [b for b in histories[name] if b.start + 3600 <= as_of][-25:]
        expected = [as_of - i * 3600 for i in range(25, 0, -1)]
        if [b.start for b in bars] != expected:
            return result
        returns[name] = [math.log(b.close / a.close) for a, b in zip(bars, bars[1:])]
        if not all(math.isfinite(r) for r in returns[name]):
            return result
    pairs = [correlation(returns[a], returns[b]) for i, a in enumerate(CORE_SYMBOLS)
             for b in CORE_SYMBOLS[i+1:]]
    own = returns[symbol]
    prior_var = covariance(own[:-6], own[:-6])
    result.update(status='AVAILABLE', values={
        'corr_btc24': correlation(own, returns['BTCUSDT']),
        'corr_eth24': correlation(own, returns['ETHUSDT']),
        'core_mean_pair_corr24': sum(pairs) / 3 if all(p is not None for p in pairs) else None,
        'vol6_to_prior18': math.sqrt(covariance(own[-6:], own[-6:]) / prior_var) if prior_var > 0 else None},
        covariance_matrix=[[covariance(returns[a], returns[b]) for b in CORE_SYMBOLS] for a in CORE_SYMBOLS])
    return result
