from __future__ import annotations

import csv
import json
import math
import sqlite3
from collections import OrderedDict
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from btc_eth_15m.config import AppConfig

UTC = timezone.utc

TARGET_DAILY_RETURN_MIN_PCT = 5.0
TARGET_DAILY_RETURN_MAX_PCT = 7.0

ETH_SHORT_VARIANTS: list[tuple[str, dict[str, Any], dict[str, Any]]] = [
    (
        "dt_eth_short_gap300",
        {"mode": "trend_pullback", "side_filter": "short", "min_signal_htf_gap_bps": 300.0, "stop_atr_mult": 1.2, "reward_risk": 2.0},
        {"symbols": ["ETHUSDT"], "max_hold_bars": 12},
    ),
    (
        "dt_eth_short_volume15",
        {"mode": "trend_pullback", "side_filter": "short", "min_signal_htf_gap_bps": 190.0, "min_signal_volume_ratio": 1.5, "stop_atr_mult": 1.2, "reward_risk": 2.0},
        {"symbols": ["ETHUSDT"], "max_hold_bars": 12},
    ),
    (
        "dt_eth_short_mid_atr",
        {"mode": "trend_pullback", "side_filter": "short", "min_signal_htf_gap_bps": 190.0, "min_signal_atr_pct": 0.0059, "max_signal_atr_pct": 0.0120, "stop_atr_mult": 1.2, "reward_risk": 2.0},
        {"symbols": ["ETHUSDT"], "max_hold_bars": 12},
    ),
    (
        "dt_eth_short_regime_mid",
        {"mode": "trend_pullback", "side_filter": "short", "min_signal_htf_gap_bps": 190.0, "min_signal_regime_atr_pct": 0.0059, "max_signal_regime_atr_pct": 0.0102, "stop_atr_mult": 1.2, "reward_risk": 2.0},
        {"symbols": ["ETHUSDT"], "max_hold_bars": 12},
    ),
    (
        "dt_eth_short_hour15_16",
        {"mode": "trend_pullback", "side_filter": "short", "min_signal_htf_gap_bps": 190.0, "signal_start_hour_utc": 15, "signal_end_hour_utc": 16, "stop_atr_mult": 1.2, "reward_risk": 2.0},
        {"symbols": ["ETHUSDT"], "max_hold_bars": 12},
    ),
    (
        "dt_eth_short_hour21_23",
        {"mode": "trend_pullback", "side_filter": "short", "min_signal_htf_gap_bps": 190.0, "signal_start_hour_utc": 21, "signal_end_hour_utc": 23, "stop_atr_mult": 1.2, "reward_risk": 2.0},
        {"symbols": ["ETHUSDT"], "max_hold_bars": 12},
    ),
]

TRADE_FIELDS = [
    "symbol",
    "side",
    "entry_time",
    "exit_time",
    "entry_price",
    "exit_price",
    "qty",
    "stop",
    "target",
    "gross_pnl",
    "fees",
    "net_pnl",
    "r_multiple",
    "exit_reason",
    "hold_bars",
    "signal_time",
    "signal_close",
    "signal_rsi",
    "signal_atr_pct",
    "signal_regime_atr_pct",
    "signal_volume_ratio",
    "signal_htf_gap_bps",
    "signal_distance_ema_mid_atr",
    "signal_hour_utc",
]


def run_stdlib_eth_short_sweep(config: AppConfig, variant_names: list[str] | None = None) -> Path:
    variants = ETH_SHORT_VARIANTS
    if variant_names:
        requested = set(variant_names)
        variants = [variant for variant in variants if variant[0] in requested]
        if len(variants) != len(requested):
            found = {variant[0] for variant in variants}
            missing = sorted(requested - found)
            raise ValueError(f"Unknown stdlib sweep variant(s): {', '.join(missing)}")

    rows = []
    sweep_id = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    for index, (name, strategy_overrides, app_overrides) in enumerate(variants, start=1):
        print(f"[{index}/{len(variants)}] running {name}", flush=True)
        variant_config = _variant_config(config, strategy_overrides, app_overrides)
        result = run_stdlib_backtest(variant_config)
        summary = result["summary"]
        daily = summary.get("daily_return_stats", {})
        rows.append(
            {
                "sweep_id": sweep_id,
                "variant": name,
                "run_id": summary["run_id"],
                "trade_count": summary["trade_count"],
                "final_equity": summary["final_equity"],
                "total_return_pct": summary["total_return_pct"],
                "max_drawdown_pct": summary["max_drawdown_pct"],
                "win_rate_pct": summary["win_rate_pct"],
                "profit_factor": summary["profit_factor"],
                "expectancy": summary["expectancy"],
                "avg_r": summary["avg_r"],
                "avg_daily_return_pct": daily.get("avg_daily_return_pct", 0.0),
                "target_range_hit_rate_pct": daily.get("target_range_hit_rate_pct", 0.0),
                "above_target_min_rate_pct": daily.get("above_target_min_rate_pct", 0.0),
                "loss_day_rate_pct": daily.get("loss_day_rate_pct", 0.0),
                "strategy_overrides": json.dumps(strategy_overrides, sort_keys=True),
                "app_overrides": json.dumps(app_overrides, sort_keys=True),
            }
        )

    rows.sort(key=lambda row: (row["avg_r"], row["profit_factor"]), reverse=True)
    config.outputs_dir.mkdir(parents=True, exist_ok=True)
    csv_path = config.outputs_dir / f"{sweep_id}-sweep.csv"
    md_path = config.outputs_dir / f"{sweep_id}-sweep.md"
    _write_csv(csv_path, rows)
    md_path.write_text(_render_sweep_markdown(rows), encoding="utf-8")
    return md_path


def run_stdlib_backtest(config: AppConfig) -> dict[str, Any]:
    if config.strategy.mode != "trend_pullback":
        raise ValueError("stdlib backtest currently supports trend_pullback only.")

    frames: dict[str, list[dict[str, Any]]] = {}
    data_quality = {}
    for symbol in config.symbols:
        bars = _load_bars(config, symbol)
        if not bars:
            raise RuntimeError(f"No klines found for {symbol}. Run fetch first.")
        _add_trend_pullback_signals(bars, config)
        frames[symbol] = bars
        interval_ms = interval_to_millis(config.interval)
        expected = ((int(bars[-1]["open_time"]) - int(bars[0]["open_time"])) // interval_ms) + 1
        data_quality[symbol] = {
            "rows": len(bars),
            "missing_bars": max(0, expected - len(bars)),
            "first_bar": str(_iso_from_millis(int(bars[0]["open_time"]))),
            "last_bar": str(_iso_from_millis(int(bars[-1]["open_time"]))),
        }

    all_times = sorted({int(row["open_time"]) for frame in frames.values() for row in frame})
    row_by_time = {
        symbol: {int(row["open_time"]): row for row in frame}
        for symbol, frame in frames.items()
    }
    pending = {symbol: None for symbol in config.symbols}
    positions: dict[str, dict[str, Any]] = {}
    trades: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    realized_equity = float(config.initial_equity)
    peak_equity = realized_equity
    day_start_equity = realized_equity
    current_day = None

    for open_time in all_times:
        bar_dt = datetime.fromtimestamp(open_time / 1000, tz=UTC)
        day = bar_dt.date().isoformat()
        if current_day != day:
            current_day = day
            day_start_equity = realized_equity

        daily_loss_hit = realized_equity <= day_start_equity * (1 - config.max_daily_loss)

        for symbol in config.symbols:
            row = row_by_time[symbol].get(open_time)
            if row is None:
                continue
            if pending[symbol] is not None and symbol not in positions and not daily_loss_hit:
                maybe_position = _open_position(config, symbol, row, pending[symbol], realized_equity)
                if maybe_position is not None:
                    positions[symbol] = maybe_position
                    realized_equity -= maybe_position["entry_fee"]
            pending[symbol] = None

        for symbol in list(positions.keys()):
            row = row_by_time[symbol].get(open_time)
            if row is None:
                continue
            position = positions[symbol]
            position["hold_bars"] += 1
            exit_price, reason = _exit_check(config, position, row)
            if exit_price is None:
                continue
            trade = _close_position(position, row, exit_price, str(reason), config)
            realized_equity += trade["gross_pnl"] - (trade["fees"] - position["entry_fee"])
            trades.append(trade)
            del positions[symbol]

        mark_equity = realized_equity + _unrealized_total(positions, row_by_time, open_time)
        peak_equity = max(peak_equity, mark_equity)
        equity_curve.append(
            {
                "time": datetime.fromtimestamp(open_time / 1000, tz=UTC).isoformat(),
                "equity": mark_equity,
                "drawdown_pct": (mark_equity / peak_equity - 1) if peak_equity else 0.0,
                "open_positions": len(positions),
            }
        )

        for symbol in config.symbols:
            row = row_by_time[symbol].get(open_time)
            if row is None:
                continue
            if int(row.get("signal") or 0) != 0 and symbol not in positions:
                pending[symbol] = row

    for symbol, position in list(positions.items()):
        row = frames[symbol][-1]
        exit_price = _slipped_exit_price(float(row["close"]), int(position["side"]), config.slippage_bps)
        trade = _close_position(position, row, exit_price, "end_of_data", config)
        realized_equity += trade["gross_pnl"] - (trade["fees"] - position["entry_fee"])
        trades.append(trade)
        del positions[symbol]

    run_id = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    run_dir = config.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(run_dir / "trades.csv", trades, fieldnames=TRADE_FIELDS)
    _write_csv(run_dir / "equity.csv", equity_curve, fieldnames=["time", "equity", "drawdown_pct", "open_positions"])
    summary = _summarize(config, run_id, trades, equity_curve, data_quality)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return {"run_id": run_id, "run_dir": run_dir, "trades": trades, "equity": equity_curve, "summary": summary}


def _load_bars(config: AppConfig, symbol: str) -> list[dict[str, Any]]:
    try:
        with _connect_readonly(config.db_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT symbol, interval, open_time, open_time_iso, close_time,
                       open, high, low, close, volume, quote_volume, trades
                FROM klines
                WHERE symbol = ? AND interval = ?
                ORDER BY open_time ASC
                """,
                (symbol, config.interval),
            ).fetchall()
    except sqlite3.Error as exc:
        raise RuntimeError(f"Failed to load klines: {exc}") from exc
    return [dict(row) for row in rows]


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{Path(db_path)}?mode=ro", uri=True, timeout=5)
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def interval_to_millis(interval: str) -> int:
    unit = interval[-1]
    value = int(interval[:-1])
    factors = {
        "m": 60_000,
        "h": 3_600_000,
        "d": 86_400_000,
    }
    if unit not in factors:
        raise ValueError(f"Unsupported interval: {interval}")
    return value * factors[unit]


def _add_trend_pullback_signals(bars: list[dict[str, Any]], config: AppConfig) -> None:
    strategy = config.strategy
    close = [float(row["close"]) for row in bars]
    high = [float(row["high"]) for row in bars]
    low = [float(row["low"]) for row in bars]
    volume = [float(row["volume"]) for row in bars]
    ema_fast = _ewm(close, alpha=2 / (strategy.ema_fast + 1), min_periods=strategy.ema_fast)
    ema_mid = _ewm(close, alpha=2 / (strategy.ema_mid + 1), min_periods=strategy.ema_mid)
    ema_slow = _ewm(close, alpha=2 / (strategy.ema_slow + 1), min_periods=strategy.ema_slow)
    htf_ema_fast = _ewm(close, alpha=2 / (strategy.htf_ema_fast * strategy.trend_timeframe_bars + 1), min_periods=strategy.htf_ema_fast * strategy.trend_timeframe_bars)
    htf_ema_slow = _ewm(close, alpha=2 / (strategy.htf_ema_slow * strategy.trend_timeframe_bars + 1), min_periods=strategy.htf_ema_slow * strategy.trend_timeframe_bars)
    atr_values = _atr(high, low, close, strategy.atr_period)
    atr_pct = [_safe_div(value, price) for value, price in zip(atr_values, close)]
    rsi_values = _rsi(close, strategy.rsi_period)
    volume_sma = _rolling_mean(volume, strategy.volume_period)
    regime_atr_pct = _rolling_median(atr_pct, strategy.regime_lookback)
    htf_gap_bps = [
        _safe_div(abs(fast - slow), price) * 10_000 if fast is not None and slow is not None and price else None
        for fast, slow, price in zip(htf_ema_fast, htf_ema_slow, close)
    ]
    volume_ratio = [_safe_div(value, avg) for value, avg in zip(volume, volume_sma)]

    short_pullback_raw = []
    long_pullback_raw = []
    for i in range(len(bars)):
        atr_value = atr_values[i]
        if ema_fast[i] is None or ema_mid[i] is None or atr_value is None:
            short_pullback_raw.append(False)
            long_pullback_raw.append(False)
            continue
        long_pullback_raw.append(low[i] <= ema_fast[i] and low[i] >= (ema_mid[i] - 0.25 * atr_value))
        short_pullback_raw.append(high[i] >= ema_fast[i] and high[i] <= (ema_mid[i] + 0.25 * atr_value))
    long_pullback = _rolling_any(long_pullback_raw, strategy.pullback_lookback)
    short_pullback = _rolling_any(short_pullback_raw, strategy.pullback_lookback)

    for i, row in enumerate(bars):
        row["open_datetime"] = datetime.fromtimestamp(int(row["open_time"]) / 1000, tz=UTC).isoformat()
        row[f"ema{strategy.ema_fast}"] = ema_fast[i]
        row[f"ema{strategy.ema_mid}"] = ema_mid[i]
        row[f"ema{strategy.ema_slow}"] = ema_slow[i]
        row["htf_ema_fast"] = htf_ema_fast[i]
        row["htf_ema_slow"] = htf_ema_slow[i]
        row["atr"] = atr_values[i]
        row["atr_pct"] = atr_pct[i]
        row["rsi"] = rsi_values[i]
        row["volume_sma"] = volume_sma[i]
        row["regime_atr_pct"] = regime_atr_pct[i]
        row["htf_gap_bps"] = htf_gap_bps[i]
        row["volume_ratio"] = volume_ratio[i]

        signal = 0
        mid = ema_mid[i]
        slow = ema_slow[i]
        fast = ema_fast[i]
        atr_value = atr_values[i]
        rsi_value = rsi_values[i]
        vol_avg = volume_sma[i]
        if (
            mid is not None
            and slow is not None
            and fast is not None
            and atr_value is not None
            and rsi_value is not None
            and vol_avg is not None
            and i >= strategy.ema_slope_bars
            and ema_mid[i - strategy.ema_slope_bars] is not None
        ):
            trend_gap_bps = abs(mid - slow) / close[i] * 10_000 if close[i] else 0.0
            mid_slope = mid - float(ema_mid[i - strategy.ema_slope_bars])
            enough_gap = trend_gap_bps >= strategy.min_trend_gap_bps
            volume_ok = volume[i] >= vol_avg * strategy.min_volume_ratio
            long_extension_ok = close[i] <= fast + strategy.max_extension_atr * atr_value
            short_extension_ok = close[i] >= fast - strategy.max_extension_atr * atr_value
            long_signal = (
                mid > slow
                and enough_gap
                and mid_slope > 0
                and close[i] > mid
                and long_pullback[i]
                and close[i] > fast
                and 45 <= rsi_value <= 70
                and volume_ok
                and long_extension_ok
            )
            short_signal = (
                mid < slow
                and enough_gap
                and mid_slope < 0
                and close[i] < mid
                and short_pullback[i]
                and close[i] < fast
                and 30 <= rsi_value <= 55
                and volume_ok
                and short_extension_ok
            )
            signal = 1 if long_signal else -1 if short_signal else 0

        if not _post_signal_allowed(row, signal, config):
            signal = 0
        row["signal"] = signal
        row["signal_atr"] = atr_value


def _post_signal_allowed(row: dict[str, Any], signal: int, config: AppConfig) -> bool:
    strategy = config.strategy
    if strategy.side_filter == "long" and signal < 0:
        return False
    if strategy.side_filter == "short" and signal > 0:
        return False
    if strategy.side_filter not in {"long", "short", "both"}:
        raise ValueError(f"Unsupported side filter: {strategy.side_filter}")
    if (row.get("htf_gap_bps") or 0.0) < strategy.min_signal_htf_gap_bps:
        return False
    if not _between(row.get("atr_pct"), strategy.min_signal_atr_pct, strategy.max_signal_atr_pct):
        return False
    if not _between(row.get("regime_atr_pct"), strategy.min_signal_regime_atr_pct, strategy.max_signal_regime_atr_pct):
        return False
    if (row.get("volume_ratio") or 0.0) < strategy.min_signal_volume_ratio:
        return False
    hour = datetime.fromtimestamp(int(row["open_time"]) / 1000, tz=UTC).hour
    start = int(strategy.signal_start_hour_utc)
    end = int(strategy.signal_end_hour_utc)
    if start <= end:
        return start <= hour <= end
    return hour >= start or hour <= end


def _open_position(config: AppConfig, symbol: str, row: dict[str, Any], signal_row: dict[str, Any], equity: float) -> dict[str, Any] | None:
    side = int(signal_row["signal"])
    atr_value = signal_row.get("signal_atr")
    if side == 0 or atr_value is None or atr_value <= 0:
        return None
    open_price = float(row["open"])
    entry_price = _slipped_entry_price(open_price, side, config.slippage_bps)
    stop_distance = config.strategy.stop_atr_mult * float(atr_value)
    if stop_distance <= 0:
        return None
    stop = entry_price - stop_distance if side == 1 else entry_price + stop_distance
    target = entry_price + config.strategy.reward_risk * stop_distance if side == 1 else entry_price - config.strategy.reward_risk * stop_distance
    risk_amount = equity * config.risk_per_trade
    qty_by_risk = risk_amount / stop_distance
    max_notional = equity * config.max_notional_leverage
    qty_by_notional = max_notional / entry_price
    qty = min(qty_by_risk, qty_by_notional)
    if qty <= 0:
        return None
    entry_fee = abs(entry_price * qty) * config.fee_bps / 10_000
    return {
        "symbol": symbol,
        "side": side,
        "entry_time": int(row["open_time"]),
        "entry_iso": datetime.fromtimestamp(int(row["open_time"]) / 1000, tz=UTC).isoformat(),
        "entry_price": entry_price,
        "qty": qty,
        "stop": stop,
        "target": target,
        "entry_atr": atr_value,
        "entry_fee": entry_fee,
        "signal_time": signal_row["open_datetime"],
        "signal_close": float(signal_row["close"]),
        "signal_rsi": _or_nan(signal_row.get("rsi")),
        "signal_atr_pct": _or_nan(signal_row.get("atr_pct")),
        "signal_regime_atr_pct": _or_nan(signal_row.get("regime_atr_pct")),
        "signal_volume_ratio": _or_nan(signal_row.get("volume_ratio")),
        "signal_htf_gap_bps": _or_nan(signal_row.get("htf_gap_bps")),
        "signal_distance_ema_mid_atr": _distance_ema_mid_atr(signal_row, float(atr_value), config),
        "signal_hour_utc": datetime.fromtimestamp(int(signal_row["open_time"]) / 1000, tz=UTC).hour,
        "hold_bars": 0,
    }


def _exit_check(config: AppConfig, position: dict[str, Any], row: dict[str, Any]) -> tuple[float | None, str | None]:
    high = float(row["high"])
    low = float(row["low"])
    close = float(row["close"])
    side = int(position["side"])
    if side == 1:
        stop_hit = low <= position["stop"]
        target_hit = high >= position["target"]
    else:
        stop_hit = high >= position["stop"]
        target_hit = low <= position["target"]

    if stop_hit:
        return _slipped_exit_price(float(position["stop"]), side, config.slippage_bps), "stop"
    if target_hit:
        return _slipped_exit_price(float(position["target"]), side, config.slippage_bps), "target"
    if int(position["hold_bars"]) >= config.max_hold_bars:
        return _slipped_exit_price(close, side, config.slippage_bps), "time"
    return None, None


def _close_position(position: dict[str, Any], row: dict[str, Any], exit_price: float, reason: str, config: AppConfig) -> dict[str, Any]:
    side = int(position["side"])
    gross = (exit_price - float(position["entry_price"])) * float(position["qty"]) * side
    exit_fee = abs(exit_price * float(position["qty"])) * config.fee_bps / 10_000
    total_fees = float(position["entry_fee"]) + exit_fee
    net = gross - total_fees
    initial_risk = abs(float(position["entry_price"]) - float(position["stop"])) * float(position["qty"])
    r_multiple = net / initial_risk if initial_risk else 0.0
    return {
        "symbol": position["symbol"],
        "side": "long" if side == 1 else "short",
        "entry_time": position["entry_iso"],
        "exit_time": datetime.fromtimestamp(int(row["open_time"]) / 1000, tz=UTC).isoformat(),
        "entry_price": position["entry_price"],
        "exit_price": exit_price,
        "qty": position["qty"],
        "stop": position["stop"],
        "target": position["target"],
        "gross_pnl": gross,
        "fees": total_fees,
        "net_pnl": net,
        "r_multiple": r_multiple,
        "exit_reason": reason,
        "hold_bars": position["hold_bars"],
        "signal_time": position["signal_time"],
        "signal_close": position["signal_close"],
        "signal_rsi": position["signal_rsi"],
        "signal_atr_pct": position["signal_atr_pct"],
        "signal_regime_atr_pct": position["signal_regime_atr_pct"],
        "signal_volume_ratio": position["signal_volume_ratio"],
        "signal_htf_gap_bps": position["signal_htf_gap_bps"],
        "signal_distance_ema_mid_atr": position["signal_distance_ema_mid_atr"],
        "signal_hour_utc": position["signal_hour_utc"],
    }


def _summarize(config: AppConfig, run_id: str, trades: list[dict[str, Any]], equity: list[dict[str, Any]], data_quality: dict[str, Any]) -> dict[str, Any]:
    final_equity = float(config.initial_equity + sum(float(trade["net_pnl"]) for trade in trades))
    wins = [trade for trade in trades if float(trade["net_pnl"]) > 0]
    losses = [trade for trade in trades if float(trade["net_pnl"]) < 0]
    gross_profit = sum(float(trade["net_pnl"]) for trade in wins)
    gross_loss = abs(sum(float(trade["net_pnl"]) for trade in losses))
    profit_factor = gross_profit / gross_loss if gross_loss else float("inf") if gross_profit else 0.0
    by_symbol = _grouped_stats(trades, lambda trade: str(trade["symbol"]))
    by_side = _grouped_stats(trades, lambda trade: str(trade["side"]))
    by_symbol_side = _grouped_stats(trades, lambda trade: f"{trade['symbol']}:{trade['side']}")
    by_year = _grouped_stats(trades, lambda trade: str(trade["entry_time"])[:4])
    by_exit = _grouped_stats(trades, lambda trade: str(trade["exit_reason"]))
    return {
        "run_id": run_id,
        "symbols": ",".join(config.symbols),
        "strategy": asdict(config.strategy),
        "trade_count": len(trades),
        "final_equity": final_equity,
        "total_return_pct": (final_equity / config.initial_equity - 1) * 100,
        "max_drawdown_pct": min((float(row["drawdown_pct"]) for row in equity), default=0.0) * 100,
        "win_rate_pct": (len(wins) / len(trades) * 100) if trades else 0.0,
        "profit_factor": profit_factor,
        "expectancy": (sum(float(trade["net_pnl"]) for trade in trades) / len(trades)) if trades else 0.0,
        "avg_r": (sum(float(trade["r_multiple"]) for trade in trades) / len(trades)) if trades else 0.0,
        "by_symbol": by_symbol,
        "by_side": by_side,
        "by_symbol_side": by_symbol_side,
        "by_year": by_year,
        "by_exit": by_exit,
        "daily_return_stats": _daily_return_stats(equity, config.initial_equity),
        "data_quality": data_quality,
    }


def _grouped_stats(trades: list[dict[str, Any]], key_func) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for trade in trades:
        groups.setdefault(key_func(trade), []).append(trade)
    return {key: _group_stats(group) for key, group in groups.items()}


def _group_stats(group: list[dict[str, Any]]) -> dict[str, Any]:
    wins = [trade for trade in group if float(trade["net_pnl"]) > 0]
    return {
        "trades": len(group),
        "net_pnl": sum(float(trade["net_pnl"]) for trade in group),
        "win_rate_pct": (len(wins) / len(group) * 100) if group else 0.0,
        "avg_r": (sum(float(trade["r_multiple"]) for trade in group) / len(group)) if group else 0.0,
    }


def _daily_return_stats(equity: list[dict[str, Any]], initial_equity: float) -> dict[str, Any]:
    base = {
        "target_min_pct": TARGET_DAILY_RETURN_MIN_PCT,
        "target_max_pct": TARGET_DAILY_RETURN_MAX_PCT,
        "trading_days": 0,
        "avg_daily_return_pct": 0.0,
        "median_daily_return_pct": 0.0,
        "best_daily_return_pct": 0.0,
        "worst_daily_return_pct": 0.0,
        "target_range_hit_rate_pct": 0.0,
        "above_target_min_rate_pct": 0.0,
        "above_target_max_rate_pct": 0.0,
        "loss_day_rate_pct": 0.0,
    }
    if not equity:
        return base
    daily_close: OrderedDict[str, float] = OrderedDict()
    for row in equity:
        daily_close[str(row["time"])[:10]] = float(row["equity"])
    returns = []
    previous = initial_equity
    for value in daily_close.values():
        if previous > 0:
            returns.append((value / previous - 1) * 100)
        previous = value
    if not returns:
        return base
    in_target = [value for value in returns if TARGET_DAILY_RETURN_MIN_PCT <= value <= TARGET_DAILY_RETURN_MAX_PCT]
    return {
        "target_min_pct": TARGET_DAILY_RETURN_MIN_PCT,
        "target_max_pct": TARGET_DAILY_RETURN_MAX_PCT,
        "trading_days": len(returns),
        "avg_daily_return_pct": sum(returns) / len(returns),
        "median_daily_return_pct": median(returns),
        "best_daily_return_pct": max(returns),
        "worst_daily_return_pct": min(returns),
        "target_range_hit_rate_pct": len(in_target) / len(returns) * 100,
        "above_target_min_rate_pct": len([value for value in returns if value >= TARGET_DAILY_RETURN_MIN_PCT]) / len(returns) * 100,
        "above_target_max_rate_pct": len([value for value in returns if value > TARGET_DAILY_RETURN_MAX_PCT]) / len(returns) * 100,
        "loss_day_rate_pct": len([value for value in returns if value < 0]) / len(returns) * 100,
    }


def _ewm(values: list[float | None], *, alpha: float, min_periods: int) -> list[float | None]:
    out: list[float | None] = []
    current = None
    count = 0
    for value in values:
        if value is None:
            out.append(None)
            continue
        current = value if current is None else alpha * value + (1 - alpha) * current
        count += 1
        out.append(current if count >= min_periods else None)
    return out


def _atr(high: list[float], low: list[float], close: list[float], period: int) -> list[float | None]:
    true_range = []
    previous_close = None
    for h_value, l_value, c_value in zip(high, low, close):
        values = [h_value - l_value]
        if previous_close is not None:
            values.append(abs(h_value - previous_close))
            values.append(abs(l_value - previous_close))
        true_range.append(max(values))
        previous_close = c_value
    return _ewm(true_range, alpha=1 / period, min_periods=period)


def _rsi(close: list[float], period: int) -> list[float]:
    deltas: list[float | None] = [None]
    deltas.extend(close[index] - close[index - 1] for index in range(1, len(close)))
    gain = [max(value, 0.0) if value is not None else None for value in deltas]
    loss = [-min(value, 0.0) if value is not None else None for value in deltas]
    avg_gain = _ewm(gain, alpha=1 / period, min_periods=period)
    avg_loss = _ewm(loss, alpha=1 / period, min_periods=period)
    output = []
    for gain_value, loss_value in zip(avg_gain, avg_loss):
        if gain_value is None or loss_value is None or loss_value == 0:
            output.append(100.0)
        else:
            rs = gain_value / loss_value
            output.append(100 - (100 / (1 + rs)))
    return output


def _rolling_mean(values: list[float], window: int) -> list[float | None]:
    out: list[float | None] = []
    running = 0.0
    queue: list[float] = []
    for value in values:
        queue.append(value)
        running += value
        if len(queue) > window:
            running -= queue.pop(0)
        out.append(running / window if len(queue) >= window else None)
    return out


def _rolling_median(values: list[float | None], window: int) -> list[float | None]:
    out: list[float | None] = []
    queue: list[float | None] = []
    for value in values:
        queue.append(value)
        if len(queue) > window:
            queue.pop(0)
        clean = [item for item in queue if item is not None]
        out.append(median(clean) if len(clean) >= window else None)
    return out


def _rolling_any(values: list[bool], window: int) -> list[bool]:
    out = []
    queue: list[bool] = []
    for value in values:
        queue.append(value)
        if len(queue) > window:
            queue.pop(0)
        out.append(any(queue))
    return out


def _variant_config(config: AppConfig, strategy_overrides: dict[str, Any], app_overrides: dict[str, Any]) -> AppConfig:
    strategy = replace(config.strategy, **strategy_overrides)
    return replace(config, strategy=strategy, **app_overrides)


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    fieldnames = fieldnames or (list(rows[0]) if rows else [])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _render_sweep_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# BTC/ETH 15m Parameter Sweep",
        "",
        "| Variant | Trades | PF | Avg R | Avg Daily | 5%-7% Days | >=5% Days | Loss Days | Return | Max DD | Win Rate | Run ID |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['variant']} | {row['trade_count']} | {row['profit_factor']:.3f} | {row['avg_r']:.3f} | "
            f"{row['avg_daily_return_pct']:.3f}% | {row['target_range_hit_rate_pct']:.2f}% | "
            f"{row['above_target_min_rate_pct']:.2f}% | {row['loss_day_rate_pct']:.2f}% | "
            f"{row['total_return_pct']:.2f}% | {row['max_drawdown_pct']:.2f}% | {row['win_rate_pct']:.2f}% | `{row['run_id']}` |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- This sweep is for research only and does not send orders.",
            "- Prefer variants with positive Avg R and PF > 1 before considering paper trading.",
            "- A variant with fewer trades but less negative Avg R is useful evidence for the next research branch, not a live-trading approval.",
        ]
    )
    return "\n".join(lines) + "\n"


def _unrealized_total(positions: dict[str, dict[str, Any]], row_by_time: dict[str, dict[int, dict[str, Any]]], open_time: int) -> float:
    total = 0.0
    for symbol, position in positions.items():
        row = row_by_time[symbol].get(open_time)
        if row is not None:
            total += (float(row["close"]) - float(position["entry_price"])) * float(position["qty"]) * int(position["side"])
    return total


def _slipped_entry_price(price: float, side: int, slippage_bps: float) -> float:
    multiplier = 1 + slippage_bps / 10_000 if side == 1 else 1 - slippage_bps / 10_000
    return price * multiplier


def _slipped_exit_price(price: float, side: int, slippage_bps: float) -> float:
    multiplier = 1 - slippage_bps / 10_000 if side == 1 else 1 + slippage_bps / 10_000
    return price * multiplier


def _distance_ema_mid_atr(row: dict[str, Any], atr_value: float, config: AppConfig) -> float:
    ema_mid = row.get(f"ema{config.strategy.ema_mid}")
    if ema_mid is None or atr_value == 0:
        return math.nan
    return (float(row["close"]) - float(ema_mid)) / atr_value


def _between(value: Any, lower: float, upper: float) -> bool:
    return value is not None and lower <= float(value) <= upper


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _or_nan(value: Any) -> float:
    return math.nan if value is None else float(value)


def _iso_from_millis(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()
