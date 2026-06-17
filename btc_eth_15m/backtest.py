from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd

from btc_eth_15m.config import AppConfig
from btc_eth_15m.data import load_klines, missing_bars
from btc_eth_15m.strategy import generate_signals

TARGET_DAILY_RETURN_MIN_PCT = 5.0
TARGET_DAILY_RETURN_MAX_PCT = 7.0


@dataclass
class Position:
    symbol: str
    side: int
    entry_time: int
    entry_iso: str
    entry_price: float
    qty: float
    stop: float
    target: float
    entry_atr: float
    entry_fee: float
    signal_time: str
    signal_close: float
    signal_rsi: float
    signal_atr_pct: float
    signal_regime_atr_pct: float
    signal_volume_ratio: float
    signal_htf_gap_bps: float
    signal_distance_ema_mid_atr: float
    signal_hour_utc: int
    hold_bars: int = 0


@dataclass
class Trade:
    symbol: str
    side: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    qty: float
    stop: float
    target: float
    gross_pnl: float
    fees: float
    net_pnl: float
    r_multiple: float
    exit_reason: str
    hold_bars: int
    signal_time: str
    signal_close: float
    signal_rsi: float
    signal_atr_pct: float
    signal_regime_atr_pct: float
    signal_volume_ratio: float
    signal_htf_gap_bps: float
    signal_distance_ema_mid_atr: float
    signal_hour_utc: int


def run_backtest(config: AppConfig) -> dict:
    frames = {}
    data_quality = {}
    for symbol in config.symbols:
        raw = load_klines(config.db_path, symbol, config.interval)
        if raw.empty:
            raise RuntimeError(f"No klines found for {symbol}. Run fetch first.")
        frames[symbol] = generate_signals(raw, config.strategy).reset_index(drop=True)
        data_quality[symbol] = {
            "rows": int(len(raw)),
            "missing_bars": missing_bars(raw, config.interval),
            "first_bar": str(raw["open_datetime"].iloc[0]),
            "last_bar": str(raw["open_datetime"].iloc[-1]),
        }

    all_times = sorted({int(row.open_time) for frame in frames.values() for row in frame.itertuples()})
    row_by_time = {
        symbol: {int(row.open_time): row for row in frame.itertuples()}
        for symbol, frame in frames.items()
    }
    previous_rows = {symbol: None for symbol in config.symbols}
    pending = {symbol: None for symbol in config.symbols}
    positions: dict[str, Position] = {}
    trades: list[Trade] = []
    equity_curve = []
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
                    realized_equity -= maybe_position.entry_fee
            pending[symbol] = None

        for symbol in list(positions.keys()):
            row = row_by_time[symbol].get(open_time)
            if row is None:
                continue
            position = positions[symbol]
            position.hold_bars += 1
            exit_price, reason = _exit_check(config, position, row)
            if exit_price is None:
                continue
            trade = _close_position(position, row, exit_price, reason, config)
            realized_equity += trade.gross_pnl - (trade.fees - position.entry_fee)
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
            previous_rows[symbol] = row
            if int(row.signal) != 0 and symbol not in positions:
                pending[symbol] = row

    # Close any remaining positions at the last available close.
    for symbol, position in list(positions.items()):
        frame = frames[symbol]
        last = frame.iloc[-1]
        row = next(frame.iloc[-1:].itertuples())
        exit_price = _slipped_exit_price(float(last["close"]), position.side, config.slippage_bps)
        trade = _close_position(position, row, exit_price, "end_of_data", config)
        realized_equity += trade.gross_pnl - (trade.fees - position.entry_fee)
        trades.append(trade)
        del positions[symbol]

    run_id = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    run_dir = config.runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    trades_frame = pd.DataFrame([asdict(trade) for trade in trades])
    equity_frame = pd.DataFrame(equity_curve)
    trades_frame.to_csv(run_dir / "trades.csv", index=False)
    equity_frame.to_csv(run_dir / "equity.csv", index=False)
    summary = summarize(config, run_id, trades_frame, equity_frame, data_quality)
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return {
        "run_id": run_id,
        "run_dir": run_dir,
        "trades": trades_frame,
        "equity": equity_frame,
        "summary": summary,
    }


def _open_position(config: AppConfig, symbol: str, row, signal_row, equity: float) -> Position | None:
    side = int(signal_row.signal)
    atr_value = float(signal_row.signal_atr)
    if side == 0 or pd.isna(atr_value) or atr_value <= 0:
        return None
    open_price = float(row.open)
    entry_price = _slipped_entry_price(open_price, side, config.slippage_bps)
    stop_distance = config.strategy.stop_atr_mult * atr_value
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
    return Position(
        symbol=symbol,
        side=side,
        entry_time=int(row.open_time),
        entry_iso=str(row.open_datetime),
        entry_price=entry_price,
        qty=qty,
        stop=stop,
        target=target,
        entry_atr=atr_value,
        entry_fee=entry_fee,
        signal_time=str(signal_row.open_datetime),
        signal_close=float(signal_row.close),
        signal_rsi=_safe_float(signal_row, "rsi"),
        signal_atr_pct=_safe_float(signal_row, "atr_pct"),
        signal_regime_atr_pct=_safe_float(signal_row, "regime_atr_pct"),
        signal_volume_ratio=_safe_ratio(_safe_float(signal_row, "volume"), _safe_float(signal_row, "volume_sma")),
        signal_htf_gap_bps=_htf_gap_bps(signal_row),
        signal_distance_ema_mid_atr=_distance_ema_mid_atr(signal_row, atr_value),
        signal_hour_utc=datetime.fromtimestamp(int(signal_row.open_time) / 1000, tz=UTC).hour,
    )


def _exit_check(config: AppConfig, position: Position, row) -> tuple[float | None, str | None]:
    high = float(row.high)
    low = float(row.low)
    close = float(row.close)
    if position.side == 1:
        stop_hit = low <= position.stop
        target_hit = high >= position.target
    else:
        stop_hit = high >= position.stop
        target_hit = low <= position.target

    if stop_hit:
        return _slipped_exit_price(position.stop, position.side, config.slippage_bps), "stop"
    if target_hit:
        return _slipped_exit_price(position.target, position.side, config.slippage_bps), "target"
    if position.hold_bars >= config.max_hold_bars:
        return _slipped_exit_price(close, position.side, config.slippage_bps), "time"
    return None, None


def _close_position(position: Position, row, exit_price: float, reason: str, config: AppConfig) -> Trade:
    gross = (exit_price - position.entry_price) * position.qty * position.side
    exit_fee = abs(exit_price * position.qty) * config.fee_bps / 10_000
    total_fees = position.entry_fee + exit_fee
    net = gross - total_fees
    initial_risk = abs(position.entry_price - position.stop) * position.qty
    r_multiple = net / initial_risk if initial_risk else 0.0
    return Trade(
        symbol=position.symbol,
        side="long" if position.side == 1 else "short",
        entry_time=position.entry_iso,
        exit_time=str(row.open_datetime),
        entry_price=position.entry_price,
        exit_price=exit_price,
        qty=position.qty,
        stop=position.stop,
        target=position.target,
        gross_pnl=gross,
        fees=total_fees,
        net_pnl=net,
        r_multiple=r_multiple,
        exit_reason=reason,
        hold_bars=position.hold_bars,
        signal_time=position.signal_time,
        signal_close=position.signal_close,
        signal_rsi=position.signal_rsi,
        signal_atr_pct=position.signal_atr_pct,
        signal_regime_atr_pct=position.signal_regime_atr_pct,
        signal_volume_ratio=position.signal_volume_ratio,
        signal_htf_gap_bps=position.signal_htf_gap_bps,
        signal_distance_ema_mid_atr=position.signal_distance_ema_mid_atr,
        signal_hour_utc=position.signal_hour_utc,
    )


def _safe_float(row, name: str) -> float:
    value = getattr(row, name, float("nan"))
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _safe_ratio(numerator: float, denominator: float) -> float:
    if pd.isna(numerator) or pd.isna(denominator) or denominator == 0:
        return float("nan")
    return numerator / denominator


def _htf_gap_bps(row) -> float:
    fast = _safe_float(row, "htf_ema_fast")
    slow = _safe_float(row, "htf_ema_slow")
    close = _safe_float(row, "close")
    if pd.isna(fast) or pd.isna(slow) or pd.isna(close) or close == 0:
        return float("nan")
    return abs(fast - slow) / close * 10_000


def _distance_ema_mid_atr(row, atr_value: float) -> float:
    close = _safe_float(row, "close")
    ema_mid = _safe_float(row, "ema50")
    if pd.isna(close) or pd.isna(ema_mid) or pd.isna(atr_value) or atr_value == 0:
        return float("nan")
    return (close - ema_mid) / atr_value


def _slipped_entry_price(price: float, side: int, slippage_bps: float) -> float:
    multiplier = 1 + slippage_bps / 10_000 if side == 1 else 1 - slippage_bps / 10_000
    return price * multiplier


def _slipped_exit_price(price: float, side: int, slippage_bps: float) -> float:
    multiplier = 1 - slippage_bps / 10_000 if side == 1 else 1 + slippage_bps / 10_000
    return price * multiplier


def _unrealized_total(positions: dict[str, Position], row_by_time: dict, open_time: int) -> float:
    total = 0.0
    for symbol, position in positions.items():
        row = row_by_time[symbol].get(open_time)
        if row is None:
            continue
        total += (float(row.close) - position.entry_price) * position.qty * position.side
    return total


def summarize(
    config: AppConfig,
    run_id: str,
    trades: pd.DataFrame,
    equity: pd.DataFrame,
    data_quality: dict,
) -> dict:
    if trades.empty:
        final_equity = config.initial_equity
        daily_return_stats = _daily_return_stats(equity, config.initial_equity)
        return {
            "run_id": run_id,
            "symbols": ",".join(config.symbols),
            "strategy": asdict(config.strategy),
            "trade_count": 0,
            "final_equity": final_equity,
            "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "win_rate_pct": 0.0,
            "profit_factor": 0.0,
            "expectancy": 0.0,
            "avg_r": 0.0,
            "by_symbol": {},
            "by_side": {},
            "by_symbol_side": {},
            "by_year": {},
            "by_exit": {},
            "daily_return_stats": daily_return_stats,
            "data_quality": data_quality,
        }

    final_equity = float(config.initial_equity + trades["net_pnl"].sum())
    wins = trades[trades["net_pnl"] > 0]
    losses = trades[trades["net_pnl"] < 0]
    gross_profit = float(wins["net_pnl"].sum())
    gross_loss = abs(float(losses["net_pnl"].sum()))
    profit_factor = gross_profit / gross_loss if gross_loss else float("inf")
    max_drawdown = float(equity["drawdown_pct"].min()) if not equity.empty else 0.0
    by_symbol = {
        symbol: {
            "trades": int(len(group)),
            "net_pnl": float(group["net_pnl"].sum()),
            "win_rate_pct": float((group["net_pnl"] > 0).mean() * 100),
            "avg_r": float(group["r_multiple"].mean()),
        }
        for symbol, group in trades.groupby("symbol")
    }
    by_side = {
        side: _group_stats(group)
        for side, group in trades.groupby("side")
    }
    by_symbol_side = {
        f"{symbol}:{side}": _group_stats(group)
        for (symbol, side), group in trades.groupby(["symbol", "side"])
    }
    dated_trades = trades.copy()
    dated_trades["year"] = pd.to_datetime(dated_trades["entry_time"], utc=True).dt.year
    by_year = {
        str(year): _group_stats(group)
        for year, group in dated_trades.groupby("year")
    }
    by_exit = {
        reason: _group_stats(group)
        for reason, group in trades.groupby("exit_reason")
    }
    daily_return_stats = _daily_return_stats(equity, config.initial_equity)
    return {
        "run_id": run_id,
        "symbols": ",".join(config.symbols),
        "strategy": asdict(config.strategy),
        "trade_count": int(len(trades)),
        "final_equity": final_equity,
        "total_return_pct": (final_equity / config.initial_equity - 1) * 100,
        "max_drawdown_pct": max_drawdown * 100,
        "win_rate_pct": float((trades["net_pnl"] > 0).mean() * 100),
        "profit_factor": profit_factor,
        "expectancy": float(trades["net_pnl"].mean()),
        "avg_r": float(trades["r_multiple"].mean()),
        "by_symbol": by_symbol,
        "by_side": by_side,
        "by_symbol_side": by_symbol_side,
        "by_year": by_year,
        "by_exit": by_exit,
        "daily_return_stats": daily_return_stats,
        "data_quality": data_quality,
    }


def _group_stats(group: pd.DataFrame) -> dict:
    return {
        "trades": int(len(group)),
        "net_pnl": float(group["net_pnl"].sum()),
        "win_rate_pct": float((group["net_pnl"] > 0).mean() * 100),
        "avg_r": float(group["r_multiple"].mean()),
    }


def _daily_return_stats(equity: pd.DataFrame, initial_equity: float) -> dict:
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
    if equity.empty or "time" not in equity or "equity" not in equity:
        return base

    daily = equity[["time", "equity"]].copy()
    daily["date"] = pd.to_datetime(daily["time"], utc=True).dt.date
    daily_close = daily.groupby("date")["equity"].last().astype(float)
    if daily_close.empty:
        return base

    previous_close = daily_close.shift(1)
    if initial_equity > 0:
        previous_close.iloc[0] = initial_equity
    daily_returns = ((daily_close / previous_close) - 1).dropna() * 100
    if daily_returns.empty:
        return base

    in_target = daily_returns.between(
        TARGET_DAILY_RETURN_MIN_PCT,
        TARGET_DAILY_RETURN_MAX_PCT,
        inclusive="both",
    )
    return {
        "target_min_pct": TARGET_DAILY_RETURN_MIN_PCT,
        "target_max_pct": TARGET_DAILY_RETURN_MAX_PCT,
        "trading_days": int(len(daily_returns)),
        "avg_daily_return_pct": float(daily_returns.mean()),
        "median_daily_return_pct": float(daily_returns.median()),
        "best_daily_return_pct": float(daily_returns.max()),
        "worst_daily_return_pct": float(daily_returns.min()),
        "target_range_hit_rate_pct": float(in_target.mean() * 100),
        "above_target_min_rate_pct": float((daily_returns >= TARGET_DAILY_RETURN_MIN_PCT).mean() * 100),
        "above_target_max_rate_pct": float((daily_returns > TARGET_DAILY_RETURN_MAX_PCT).mean() * 100),
        "loss_day_rate_pct": float((daily_returns < 0).mean() * 100),
    }
