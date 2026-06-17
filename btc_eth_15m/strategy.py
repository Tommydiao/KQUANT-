from __future__ import annotations

import numpy as np
import pandas as pd

from btc_eth_15m.config import StrategyConfig
from btc_eth_15m.indicators import atr, ema, rsi


def add_indicators(frame: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    data = frame.copy()
    data[f"ema{config.ema_fast}"] = ema(data["close"], config.ema_fast)
    data[f"ema{config.ema_mid}"] = ema(data["close"], config.ema_mid)
    data[f"ema{config.ema_slow}"] = ema(data["close"], config.ema_slow)
    data["htf_ema_fast"] = ema(data["close"], config.htf_ema_fast * config.trend_timeframe_bars)
    data["htf_ema_slow"] = ema(data["close"], config.htf_ema_slow * config.trend_timeframe_bars)
    data["atr"] = atr(data, config.atr_period)
    data["atr_pct"] = data["atr"] / data["close"]
    data["rsi"] = rsi(data["close"], config.rsi_period)
    data["volume_sma"] = data["volume"].rolling(config.volume_period, min_periods=config.volume_period).mean()
    data["regime_atr_pct"] = data["atr_pct"].rolling(config.regime_lookback, min_periods=config.regime_lookback).median()
    data["regime_trend_up"], data["regime_trend_down"] = _hourly_trend_masks(data, config)
    data["regime_range_mid"] = data["close"].rolling(config.channel_lookback, min_periods=config.channel_lookback).mean()
    data["regime_range_std"] = data["close"].rolling(config.channel_lookback, min_periods=config.channel_lookback).std()
    data["htf_gap_bps"] = (data["htf_ema_fast"] - data["htf_ema_slow"]).abs() / data["close"] * 10_000
    data["volume_ratio"] = data["volume"] / data["volume_sma"]
    return data


def generate_signals(frame: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    data = add_indicators(frame, config)
    if config.mode == "trend_pullback":
        data = _trend_pullback_signals(data, config)
    elif config.mode == "breakout_failure":
        data = _breakout_failure_signals(data, config)
    elif config.mode == "volatility_breakout":
        data = _volatility_breakout_signals(data, config)
    elif config.mode == "range_reversion":
        data = _range_reversion_signals(data, config)
    else:
        raise ValueError(f"Unsupported strategy mode: {config.mode}")
    return _apply_post_signal_filters(_apply_regime_filter(data, config), config)


def _trend_pullback_signals(data: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    ema_fast = data[f"ema{config.ema_fast}"]
    ema_mid = data[f"ema{config.ema_mid}"]
    ema_slow = data[f"ema{config.ema_slow}"]
    atr_value = data["atr"]

    trend_gap_bps = (ema_mid - ema_slow).abs() / data["close"] * 10_000
    mid_slope = ema_mid - ema_mid.shift(config.ema_slope_bars)
    enough_gap = trend_gap_bps >= config.min_trend_gap_bps

    long_pullback_raw = (data["low"] <= ema_fast) & (data["low"] >= (ema_mid - 0.25 * atr_value))
    short_pullback_raw = (data["high"] >= ema_fast) & (data["high"] <= (ema_mid + 0.25 * atr_value))
    long_pullback = long_pullback_raw.rolling(config.pullback_lookback, min_periods=1).max().astype(bool)
    short_pullback = short_pullback_raw.rolling(config.pullback_lookback, min_periods=1).max().astype(bool)

    volume_ok = data["volume"] >= data["volume_sma"] * config.min_volume_ratio
    long_extension_ok = data["close"] <= ema_fast + config.max_extension_atr * atr_value
    short_extension_ok = data["close"] >= ema_fast - config.max_extension_atr * atr_value

    long_signal = (
        (ema_mid > ema_slow)
        & enough_gap
        & (mid_slope > 0)
        & (data["close"] > ema_mid)
        & long_pullback
        & (data["close"] > ema_fast)
        & data["rsi"].between(45, 70, inclusive="both")
        & volume_ok
        & long_extension_ok
    )

    short_signal = (
        (ema_mid < ema_slow)
        & enough_gap
        & (mid_slope < 0)
        & (data["close"] < ema_mid)
        & short_pullback
        & (data["close"] < ema_fast)
        & data["rsi"].between(30, 55, inclusive="both")
        & volume_ok
        & short_extension_ok
    )

    data["signal"] = np.select([long_signal, short_signal], [1, -1], default=0)
    data["signal_atr"] = atr_value
    return data


def _hourly_trend_masks(data: pd.DataFrame, config: StrategyConfig) -> tuple[pd.Series, pd.Series]:
    fast = data["htf_ema_fast"]
    slow = data["htf_ema_slow"]
    gap_bps = (fast - slow).abs() / data["close"] * 10_000
    up = (fast > slow) & (gap_bps >= config.min_trend_gap_bps)
    down = (fast < slow) & (gap_bps >= config.min_trend_gap_bps)
    return up, down


def _breakout_failure_signals(data: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    atr_value = data["atr"]
    trend_up, trend_down = _hourly_trend_masks(data, config)
    previous_low = data["low"].rolling(config.breakout_lookback, min_periods=config.breakout_lookback).min().shift(1)
    previous_high = data["high"].rolling(config.breakout_lookback, min_periods=config.breakout_lookback).max().shift(1)
    volume_ok = data["volume"] >= data["volume_sma"] * config.min_volume_ratio
    buffer = config.breakout_buffer_atr * atr_value

    long_signal = (
        trend_up
        & volume_ok
        & (data["low"] < previous_low - buffer)
        & (data["close"] > previous_low)
        & (data["close"] > data["open"])
        & data["rsi"].between(35, 60, inclusive="both")
    )

    short_signal = (
        trend_down
        & volume_ok
        & (data["high"] > previous_high + buffer)
        & (data["close"] < previous_high)
        & (data["close"] < data["open"])
        & data["rsi"].between(40, 65, inclusive="both")
    )

    data["signal"] = np.select([long_signal, short_signal], [1, -1], default=0)
    data["signal_atr"] = atr_value
    return data


def _volatility_breakout_signals(data: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    atr_value = data["atr"]
    trend_up, trend_down = _hourly_trend_masks(data, config)
    previous_high = data["high"].rolling(config.breakout_lookback, min_periods=config.breakout_lookback).max().shift(1)
    previous_low = data["low"].rolling(config.breakout_lookback, min_periods=config.breakout_lookback).min().shift(1)
    atr_threshold = data["atr_pct"].rolling(
        config.volatility_lookback,
        min_periods=config.volatility_lookback,
    ).quantile(config.volatility_quantile)
    contraction = data["atr_pct"] <= atr_threshold
    recent_contraction = contraction.shift(1).rolling(config.contraction_lookback, min_periods=1).max().fillna(False).astype(bool)
    volume_ok = data["volume"] >= data["volume_sma"] * config.min_volume_ratio
    buffer = config.breakout_buffer_atr * atr_value

    long_signal = (
        trend_up
        & recent_contraction
        & volume_ok
        & (data["close"] > previous_high + buffer)
        & (data["close"] > data["open"])
        & data["rsi"].between(50, 75, inclusive="both")
    )

    short_signal = (
        trend_down
        & recent_contraction
        & volume_ok
        & (data["close"] < previous_low - buffer)
        & (data["close"] < data["open"])
        & data["rsi"].between(25, 50, inclusive="both")
    )

    data["signal"] = np.select([long_signal, short_signal], [1, -1], default=0)
    data["signal_atr"] = atr_value
    return data


def _range_reversion_signals(data: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    atr_value = data["atr"]
    mid = data["regime_range_mid"]
    std = data["regime_range_std"]
    upper = mid + config.channel_zscore * std
    lower = mid - config.channel_zscore * std
    volume_ok = data["volume"] >= data["volume_sma"] * config.min_volume_ratio
    range_regime = ~(data["regime_trend_up"] | data["regime_trend_down"])

    long_signal = (
        range_regime
        & volume_ok
        & (data["low"] < lower)
        & (data["close"] > lower)
        & (data["close"] > data["open"])
        & (data["rsi"] <= config.mean_reversion_rsi_long)
    )

    short_signal = (
        range_regime
        & volume_ok
        & (data["high"] > upper)
        & (data["close"] < upper)
        & (data["close"] < data["open"])
        & (data["rsi"] >= config.mean_reversion_rsi_short)
    )

    data["signal"] = np.select([long_signal, short_signal], [1, -1], default=0)
    data["signal_atr"] = atr_value
    return data


def _apply_regime_filter(data: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    if config.regime_filter == "none":
        return data
    atr_ok = data["regime_atr_pct"].between(config.min_regime_atr_pct, config.max_regime_atr_pct, inclusive="both")
    if config.regime_filter == "trend":
        trend_ok = data["regime_trend_up"] | data["regime_trend_down"]
        allowed = trend_ok & atr_ok
    elif config.regime_filter == "range":
        allowed = ~(data["regime_trend_up"] | data["regime_trend_down"]) & atr_ok
    elif config.regime_filter == "volatile":
        allowed = data["regime_atr_pct"] > config.min_regime_atr_pct
    else:
        raise ValueError(f"Unsupported regime filter: {config.regime_filter}")
    data.loc[~allowed.fillna(False), "signal"] = 0
    return data


def _apply_post_signal_filters(data: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    allowed = pd.Series(True, index=data.index)

    if config.side_filter == "long":
        allowed &= data["signal"] >= 0
    elif config.side_filter == "short":
        allowed &= data["signal"] <= 0
    elif config.side_filter != "both":
        raise ValueError(f"Unsupported side filter: {config.side_filter}")

    allowed &= data["htf_gap_bps"].fillna(0) >= config.min_signal_htf_gap_bps
    allowed &= data["atr_pct"].fillna(0).between(
        config.min_signal_atr_pct,
        config.max_signal_atr_pct,
        inclusive="both",
    )
    allowed &= data["regime_atr_pct"].fillna(0).between(
        config.min_signal_regime_atr_pct,
        config.max_signal_regime_atr_pct,
        inclusive="both",
    )
    allowed &= data["volume_ratio"].fillna(0) >= config.min_signal_volume_ratio
    allowed &= _hour_allowed(data, config)
    data.loc[~allowed, "signal"] = 0
    return data


def _hour_allowed(data: pd.DataFrame, config: StrategyConfig) -> pd.Series:
    start = int(config.signal_start_hour_utc)
    end = int(config.signal_end_hour_utc)
    if start < 0 or start > 23 or end < 0 or end > 23:
        raise ValueError("Signal UTC hour filter must be between 0 and 23.")
    if "open_datetime" not in data:
        if start == 0 and end == 23:
            return pd.Series(True, index=data.index)
        raise ValueError("Signal hour filtering requires an open_datetime column.")
    hours = data["open_datetime"].dt.hour
    if start <= end:
        return hours.between(start, end, inclusive="both")
    return (hours >= start) | (hours <= end)
