"""Initial pure hourly feature contract. Not a strategy or model consumer."""
import math

CORE_SYMBOLS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')
CROSS_DEFINITIONS = {
    'relative_btc24': 'return_24h[symbol]-return_24h[BTCUSDT]',
    'relative_eth24': 'return_24h[symbol]-return_24h[ETHUSDT]',
    'relative_core24': 'return_24h[symbol]-equal_weight_mean(core return_24h)',
    'core_positive_breadth24': 'count(core return_24h>0)/3',
}


def cross_section(snapshots, symbol, as_of):
    """No stale-peer substitution; this is three-asset breadth, not market breadth."""
    valid = symbol in CORE_SYMBOLS and set(snapshots) == set(CORE_SYMBOLS)
    returns = {}
    for name, row in snapshots.items():
        value = row.get('values', {}).get('return_24h')
        valid = valid and row.get('status') == 'AVAILABLE' and row.get('as_of') == as_of
        valid = valid and row.get('available_at') is not None and row['available_at'] <= as_of
        valid = valid and isinstance(value, (int, float)) and math.isfinite(value)
        returns[name] = value
    result = {'version': 'core_cross_section_dev_v1', 'as_of': as_of,
              'available_at': as_of, 'universe': list(CORE_SYMBOLS),
              'scope': 'THREE_CORE_ASSETS_NOT_WHOLE_MARKET',
              'status': 'UNAVAILABLE_PEER_CONTRACT',
              'values': {key: None for key in CROSS_DEFINITIONS}}
    if not valid:
        return result
    result.update(status='AVAILABLE', values={
        'relative_btc24': returns[symbol]-returns['BTCUSDT'],
        'relative_eth24': returns[symbol]-returns['ETHUSDT'],
        'relative_core24': returns[symbol]-sum(returns.values())/3,
        'core_positive_breadth24': sum(v > 0 for v in returns.values())/3})
    return result

DEFINITIONS = {
    'return_6h': 'close[t]/close[t-6]-1',
    'return_24h': 'close[t]/close[t-24]-1',
    'er24': 'abs(close[t]-close[t-24])/sum(abs(diff(close)),24)',
    'breakout_distance24': 'close[t]/max(high[t-24:t])-1',
    'relative_volume24': 'volume[t]/mean(volume[t-24:t])-1',
    'realized_vol24': 'population_sd(log_returns,last24)',
}


def snapshot(rows, as_of):
    closed = [b for b in rows if b.start + 3600 <= as_of][-25:]
    if len(closed) != 25 or closed[-1].start + 3600 != as_of or any(
            b.start - a.start != 3600 for a, b in zip(closed, closed[1:])):
        return {'status': 'MISSING_CONTIGUOUS_HISTORY', 'values': {k: None for k in DEFINITIONS}}
    c = [b.close for b in closed]
    changes = [math.log(b/a) for a, b in zip(c, c[1:])]
    mean = sum(changes)/24
    path = sum(abs(b-a) for a, b in zip(c, c[1:]))
    volume = sum(b.volume for b in closed[:-1])/24
    return {'status': 'AVAILABLE', 'as_of': as_of, 'available_at': as_of,
            'availability_basis': 'assumed_close_historical_replay',
            'timeframe': '1h', 'version': 'multifactor_ohlcv_dev_v1',
            'values': {'return_6h': c[-1]/c[-7]-1, 'return_24h': c[-1]/c[0]-1,
                       'er24': abs(c[-1]-c[0])/path if path else 0.0,
                       'breakout_distance24': c[-1]/max(b.high for b in closed[:-1])-1,
                       'relative_volume24': closed[-1].volume/volume-1 if volume else None,
                       'realized_vol24': math.sqrt(sum((v-mean)**2 for v in changes)/24)}}
