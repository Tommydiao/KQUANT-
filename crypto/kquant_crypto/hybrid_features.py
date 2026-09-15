"""Eight unscaled PIT features, observed only after the unchanged kernel."""

import math

from .candidate_policy import digest
from .hybrid_identity import economic_signal_id

FEATURE_SCHEMA = {
    'version':'hybrid_features_v1.0-m2',
    'order':['er24_1h','atr14_5m_fraction','atr14_1h_fraction','ema50_slope3_atr',
             'breakout_distance_atr','box_position','relative_btc_1h','volume20_change'],
    'formulas':{
        'er24_1h':'original kernel ER24',
        'atr14_5m_fraction':'original 5m ATR14 / signal close',
        'atr14_1h_fraction':'original 1h ATR14 / last closed 1h close',
        'ema50_slope3_atr':'original (EMA50[t]-EMA50[t-3]) / original 1h ATR14',
        'breakout_distance_atr':'(close-max(prior20 5m highs))/5m ATR; trend only',
        'box_position':'(close-frozen box lower)/box width; range only',
        'relative_btc_1h':'symbol last12 5m return minus BTC aligned last12 5m return',
        'volume20_change':'current5m volume / mean(prior20 5m volume) - 1',
    },
    'transform':'none; future training transforms must be fit on training only',
}


def snapshot(portfolio, symbol, *, available_at):
    kernel=portfolio.kernels[symbol]
    decision=portfolio.decisions[symbol]
    signal=decision.get('signal')
    if signal is None or not kernel.ready:
        raise ValueError('Only mature technical candidates have feature snapshots')
    bar=kernel.five_bars[-1]
    signal_time=bar.start+300
    if available_at<signal_time:
        raise ValueError('Feature snapshot precedes input availability')
    hour_time=kernel.hour_bars[-1].start+3600
    values={
        'er24_1h':kernel.hour.er,
        'atr14_5m_fraction':kernel.five.atr/bar.close,
        'atr14_1h_fraction':kernel.hour.atr/kernel.hour.previous_close,
        'ema50_slope3_atr':kernel.hour.slope/kernel.hour.atr,
        'breakout_distance_atr':None,'box_position':None,'relative_btc_1h':None,'volume20_change':None,
    }
    missing={}
    if signal['mode']=='UP_TREND':
        values['breakout_distance_atr']=(bar.close-max(b.high for b in kernel.five_bars[-21:-1]))/kernel.five.atr
        missing['box_position']='mode_not_applicable'
    else:
        values['box_position']=(bar.close-kernel.box['lower'])/kernel.box['width']
        missing['breakout_distance_atr']='mode_not_applicable'
    btc=portfolio.kernels['BTCUSDT'].five_bars
    if len(btc)>=13 and btc[-1].start==bar.start and btc[-13].start==kernel.five_bars[-13].start:
        values['relative_btc_1h']=bar.close/kernel.five_bars[-13].close-btc[-1].close/btc[-13].close
    else:
        missing['relative_btc_1h']='benchmark_not_aligned'
    mean=math.fsum(b.volume for b in kernel.five_bars[-21:-1])/20
    if mean>0:
        values['volume20_change']=bar.volume/mean-1
    else:
        missing['volume20_change']='prior_volume_zero'
    for name,value in values.items():
        if value is not None and not math.isfinite(value):
            raise ValueError('Nonfinite feature')
    times={name:hour_time if name in ('er24_1h','atr14_1h_fraction','ema50_slope3_atr') else signal_time for name in values}
    row={'economic_signal_id':economic_signal_id(portfolio.policy['strategy_version'],portfolio.policy['policy_hash'],
          symbol,signal['mode'],signal_time,0),'symbol':symbol,'mode':signal['mode'],'signal_time':signal_time,
         'available_at':available_at,'availability_basis':'assumed_close_historical_replay',
         'schema_hash':digest(FEATURE_SCHEMA),'values':values,'missing':missing,'factor_as_of':times,
         'source_bar_ids':[f'binance:spot:{symbol}:5m:{bar.start}',f'binance:spot:{symbol}:1h:{hour_time-3600}']}
    row['snapshot_hash']=digest(row)
    return row
