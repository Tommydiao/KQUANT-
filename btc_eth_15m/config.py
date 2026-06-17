from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class StrategyConfig:
    mode: str = "trend_pullback"
    regime_filter: str = "none"
    ema_fast: int = 20
    ema_mid: int = 50
    ema_slow: int = 200
    htf_ema_fast: int = 20
    htf_ema_slow: int = 50
    trend_timeframe_bars: int = 4
    atr_period: int = 14
    rsi_period: int = 14
    volume_period: int = 20
    pullback_lookback: int = 3
    ema_slope_bars: int = 4
    min_trend_gap_bps: float = 5.0
    stop_atr_mult: float = 1.2
    reward_risk: float = 2.0
    min_volume_ratio: float = 0.8
    max_extension_atr: float = 1.5
    breakout_lookback: int = 20
    breakout_buffer_atr: float = 0.10
    volatility_lookback: int = 96
    volatility_quantile: float = 0.25
    contraction_lookback: int = 8
    channel_lookback: int = 96
    channel_zscore: float = 1.5
    mean_reversion_rsi_long: float = 35.0
    mean_reversion_rsi_short: float = 65.0
    side_filter: str = "both"
    min_signal_htf_gap_bps: float = 0.0
    min_signal_atr_pct: float = 0.0
    max_signal_atr_pct: float = 1.0
    min_signal_regime_atr_pct: float = 0.0
    max_signal_regime_atr_pct: float = 1.0
    min_signal_volume_ratio: float = 0.0
    signal_start_hour_utc: int = 0
    signal_end_hour_utc: int = 23
    min_regime_atr_pct: float = 0.0015
    max_regime_atr_pct: float = 0.015
    regime_lookback: int = 96


@dataclass(frozen=True)
class AppConfig:
    symbols: list[str]
    interval: str = "15m"
    start: str = "2021-01-01"
    initial_equity: float = 10_000.0
    risk_per_trade: float = 0.005
    fee_bps: float = 5.0
    slippage_bps: float = 2.0
    max_positions_per_symbol: int = 1
    max_daily_loss: float = 0.02
    max_hold_bars: int = 12
    max_notional_leverage: float = 2.0
    live_enabled: bool = False
    min_execution_leverage: int = 7
    max_execution_leverage: int = 15
    live_single_order_margin_cap_usdt: float = 25.0
    live_margin_cap_usdt: float = 50.0
    live_daily_margin_cap_usdt: float = 50.0
    exchange_self_check_max_age_seconds: int = 900
    exchange_sync_max_age_seconds: int = 900
    db_path: Path = Path("work/market.sqlite3")
    runs_dir: Path = Path("work/runs")
    outputs_dir: Path = Path("outputs")
    strategy: StrategyConfig = field(default_factory=StrategyConfig)


def _strategy_config(raw: dict[str, Any] | None) -> StrategyConfig:
    raw = raw or {}
    valid = StrategyConfig.__dataclass_fields__
    return StrategyConfig(**{key: value for key, value in raw.items() if key in valid})


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    base_dir = config_path.parent.parent if config_path.parent.name == "config" else Path.cwd()
    valid = AppConfig.__dataclass_fields__
    payload = {key: value for key, value in raw.items() if key in valid and key != "strategy"}
    payload["symbols"] = [str(symbol).upper() for symbol in payload.get("symbols", [])]
    if not payload["symbols"]:
        raise ValueError("At least one symbol is required.")

    for key in ("db_path", "runs_dir", "outputs_dir"):
        if key in payload:
            payload[key] = _resolve_path(base_dir, payload[key])

    payload["strategy"] = _strategy_config(raw.get("strategy"))
    return AppConfig(**payload)


def _resolve_path(base_dir: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()
