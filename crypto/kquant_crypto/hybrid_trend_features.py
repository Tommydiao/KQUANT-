"""Streaming research wrapper around frozen baseline indicator semantics."""
from .strategy_dual_mode_v1 import _Indicators

TREND_DEFINITIONS = {
    'ema50_distance': 'close/EMA50-1; SMA50 seed then alpha=2/51',
    'ema50_slope3_atr': '(EMA50[t]-EMA50[t-3])/WilderATR14[t]',
    'atr14_fraction': 'WilderATR14/close; initial14 TR arithmetic mean',
    'positive_close_fraction24': 'count(close[i]>close[i-1],last24)/24',
    'drawdown_from_high24': 'close/max(high,last24)-1',
}


class TrendFeatures:
    def __init__(self):
        self.indicators = _Indicators()
        self.last_start = None
        self.bars = []

    def update(self, bar, as_of):
        if bar.start+3600 != as_of:
            raise ValueError('Only exact closed hourly bars accepted')
        if self.last_start is not None and bar.start <= self.last_start:
            raise ValueError('Duplicate/out-of-order hourly bar')
        if self.last_start is not None and bar.start != self.last_start+3600:
            self.indicators = _Indicators()
            self.bars = []
        self.last_start = bar.start
        self.indicators.update(bar,hourly=True)
        self.bars = (self.bars+[bar])[-25:]
        ready = self.indicators.count >= 250 and (self.indicators.atr or 0)>0
        result = {'version':'baseline_trend_features_dev_v1','status':'AVAILABLE' if ready else 'WARMUP',
                  'as_of':as_of,'available_at':as_of,'timeframe':'1h',
                  'availability_basis':'assumed_close_historical_replay',
                  'values':{k:None for k in TREND_DEFINITIONS}}
        if ready:
            h = self.indicators
            result['values'] = {
                'ema50_distance':bar.close/h.ema-1,
                'ema50_slope3_atr':h.slope/h.atr,
                'atr14_fraction':h.atr/bar.close,
                'positive_close_fraction24':sum(b.close>a.close for a,b in zip(self.bars,self.bars[1:]))/24,
                'drawdown_from_high24':bar.close/max(b.high for b in self.bars[-24:])-1}
        return result
