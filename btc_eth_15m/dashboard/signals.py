from __future__ import annotations

import hashlib
from dataclasses import replace

import pandas as pd

from btc_eth_15m.config import AppConfig
from btc_eth_15m.dashboard.models import OrderDraft, SignalSnapshot
from btc_eth_15m.dashboard.risk import (
    blocked_reasons,
    confidence_from_row,
    leverage_from_confidence,
    risk_gates,
    safe_float,
)
from btc_eth_15m.dashboard.state import (
    daily_margin_used,
    daily_loss_used,
    kill_switch_enabled,
    latest_exchange_self_check_summary,
    latest_exchange_sync_summary,
    open_margin,
    open_position_count,
)
from btc_eth_15m.data import load_recent_klines, market_freshness
from btc_eth_15m.strategy import generate_signals


def latest_signal_snapshots(config: AppConfig, mode: str = "paper") -> list[SignalSnapshot]:
    snapshots: list[SignalSnapshot] = []
    self_check_healthy = _mode_self_check_healthy(config, mode)
    sync_healthy = _mode_sync_healthy(config, mode)
    market_by_symbol = {item["symbol"]: bool(item["is_fresh"]) for item in market_freshness(config)}
    for symbol in config.symbols:
        raw = load_recent_klines(config.db_path, symbol, config.interval, limit=_signal_window(config))
        if raw.empty:
            snapshots.append(
                SignalSnapshot(
                    symbol=symbol,
                    status="missing_data",
                    bar_time=None,
                    side="flat",
                    close=None,
                    atr=None,
                    rsi=None,
                    confidence=0.0,
                    leverage=None,
                    explanation={"blockers": ["No kline data. Run fetch first."]},
                )
            )
            continue
        frame = generate_signals(raw, config.strategy)
        latest = frame.iloc[-1]
        snapshots.append(
            _snapshot_from_row(
                config,
                latest,
                mode,
                sync_healthy,
                market_by_symbol.get(symbol, False),
                self_check_healthy=self_check_healthy,
            )
        )
    return snapshots


def find_order_draft(config: AppConfig, draft_id: str, mode: str = "paper") -> OrderDraft | None:
    for snapshot in latest_signal_snapshots(config, mode):
        if snapshot.order_draft and snapshot.order_draft.id == draft_id:
            return snapshot.order_draft
    if mode == "paper":
        for draft in replay_order_drafts(config, limit=20):
            if draft.id == draft_id:
                return draft
    return None


def replay_order_drafts(config: AppConfig, *, limit: int = 4) -> list[OrderDraft]:
    """Return recent strategy-generated historical drafts for Paper lifecycle testing."""
    candidates: list[tuple[pd.Timestamp, OrderDraft]] = []
    for symbol in config.symbols:
        raw = load_recent_klines(config.db_path, symbol, config.interval, limit=_signal_window(config))
        if raw.empty:
            continue
        frame = generate_signals(raw, config.strategy)
        signal_rows = frame[frame["signal"] != 0].tail(limit * 3)
        for _, row in signal_rows.iterrows():
            side = "long" if int(row["signal"]) == 1 else "short"
            confidence, confidence_reasons = confidence_from_row(row)
            decision = leverage_from_confidence(
                confidence,
                volatility_ok=_volatility_ok(row),
                drawdown_ok=True,
                order_sync_ok=True,
                position_sync_ok=True,
                min_leverage=config.min_execution_leverage,
                max_leverage=config.max_execution_leverage,
            )
            explanation = {
                **_explanation(config, row, side, decision.reasons + confidence_reasons),
                "paper_replay": True,
                "replay_source": "recent_historical_strategy_signal",
            }
            draft = _order_draft(
                config,
                row,
                side,
                "paper",
                explanation,
                decision,
                sync_healthy=True,
                market_data_ok=True,
                self_check_healthy=True,
            )
            candidates.append((pd.Timestamp(row["open_datetime"]), replace(draft, id=f"replay-{draft.id}")))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return [draft for _, draft in candidates[:limit]]


def _snapshot_from_row(
    config: AppConfig,
    row: pd.Series,
    mode: str,
    sync_healthy: bool,
    market_data_ok: bool,
    *,
    self_check_healthy: bool | None = None,
) -> SignalSnapshot:
    signal = int(row["signal"])
    side = "long" if signal == 1 else "short" if signal == -1 else "flat"
    confidence, confidence_reasons = confidence_from_row(row)
    decision = leverage_from_confidence(
        confidence,
        volatility_ok=_volatility_ok(row),
        drawdown_ok=True,
        order_sync_ok=sync_healthy,
        position_sync_ok=sync_healthy,
        min_leverage=config.min_execution_leverage,
        max_leverage=config.max_execution_leverage,
    )
    explanation = _explanation(config, row, side, decision.reasons + confidence_reasons)
    draft = None
    if side != "flat":
        draft = _order_draft(
            config,
            row,
            side,
            mode,
            explanation,
            decision,
            sync_healthy=sync_healthy,
            market_data_ok=market_data_ok,
            self_check_healthy=sync_healthy if self_check_healthy is None else self_check_healthy,
        )
    return SignalSnapshot(
        symbol=str(row["symbol"]) if "symbol" in row else "",
        status="ok",
        bar_time=str(row["open_datetime"]),
        side=side,
        close=round(safe_float(row["close"]), 6),
        atr=round(safe_float(row["signal_atr"]), 6),
        rsi=round(safe_float(row["rsi"]), 3),
        confidence=decision.confidence,
        leverage=decision.leverage if side != "flat" else None,
        explanation=explanation,
        order_draft=draft,
    )


def _order_draft(
    config: AppConfig,
    row: pd.Series,
    side: str,
    mode: str,
    explanation: dict,
    decision,
    *,
    sync_healthy: bool,
    market_data_ok: bool,
    self_check_healthy: bool,
) -> OrderDraft:
    price = safe_float(row["close"])
    atr_value = safe_float(row["signal_atr"])
    stop_distance = max(config.strategy.stop_atr_mult * atr_value, price * 0.001)
    if side == "long":
        stop = price - stop_distance
        target = price + config.strategy.reward_risk * stop_distance
    else:
        stop = price + stop_distance
        target = price - config.strategy.reward_risk * stop_distance

    open_margin_usdt = open_margin(config.db_path, mode)
    symbol_open_positions = open_position_count(config.db_path, mode, str(row["symbol"]))
    daily_used = daily_margin_used(config.db_path, mode)
    daily_loss = daily_loss_used(config.db_path, mode)
    remaining_open = max(config.live_margin_cap_usdt - open_margin_usdt, 0.0)
    remaining_daily = max(config.live_daily_margin_cap_usdt - daily_used, 0.0)
    margin = min(config.live_single_order_margin_cap_usdt, remaining_open, remaining_daily)
    notional = margin * decision.leverage
    quantity = notional / price if price > 0 else 0.0
    gates = risk_gates(
        config,
        mode=mode,
        kill_switch=kill_switch_enabled(config.db_path),
        exchange_self_check_ok=None if mode == "paper" else self_check_healthy,
        order_sync_ok=sync_healthy,
        position_sync_ok=sync_healthy,
        market_data_ok=market_data_ok,
        api_error_ok=sync_healthy or mode == "paper",
        rate_limit_ok=True,
        open_margin_usdt=open_margin_usdt,
        daily_margin_used_usdt=daily_used,
        daily_loss_used_usdt=daily_loss,
        symbol_open_positions=symbol_open_positions,
    )
    reasons = blocked_reasons(gates)
    if margin <= 0:
        reasons.append("No margin budget remains for this mode.")
    status = "ready" if not reasons else "blocked"
    draft_id = _draft_id(str(row["symbol"]), str(row["open_datetime"]), side)
    return OrderDraft(
        id=draft_id,
        symbol=str(row["symbol"]),
        side=side,  # type: ignore[arg-type]
        mode=mode,  # type: ignore[arg-type]
        bar_time=str(row["open_datetime"]),
        entry_price=round(price, 6),
        stop_price=round(stop, 6),
        target_price=round(target, 6),
        quantity=round(quantity, 8),
        margin_usdt=round(margin, 2),
        notional_usdt=round(notional, 2),
        leverage=decision.leverage,
        max_allowed_leverage=decision.leverage,
        confidence=decision.confidence,
        status=status,  # type: ignore[arg-type]
        blocked_reasons=reasons,
        explanation={
            **explanation,
            "risk_gates": [gate.to_dict() for gate in gates],
            "margin_budget": {
                "single_order_cap_usdt": config.live_single_order_margin_cap_usdt,
                "open_margin_cap_usdt": config.live_margin_cap_usdt,
                "daily_margin_cap_usdt": config.live_daily_margin_cap_usdt,
                "open_margin_used_usdt": round(open_margin_usdt, 2),
                "daily_margin_used_usdt": round(daily_used, 2),
                "daily_loss_used_usdt": round(daily_loss, 2),
                "symbol_open_positions": symbol_open_positions,
            },
        },
    )


def _explanation(config: AppConfig, row: pd.Series, side: str, reasons: list[str]) -> dict:
    close = safe_float(row["close"])
    ema_mid = safe_float(row.get(f"ema{config.strategy.ema_mid}"))
    volume = safe_float(row.get("volume"))
    volume_sma = safe_float(row.get("volume_sma"))
    volume_ratio = volume / volume_sma if volume_sma > 0 else 0.0
    return {
        "strategy_mode": config.strategy.mode,
        "regime_filter": config.strategy.regime_filter,
        "side": side,
        "entry_timing": "next 15m candle open after manual confirmation",
        "conditions": [
            {"name": "signal", "value": int(row["signal"]), "passed": side != "flat"},
            {"name": "rsi", "value": round(safe_float(row.get("rsi")), 3), "passed": side != "flat"},
            {"name": "volume_ratio", "value": round(volume_ratio, 4), "passed": volume_ratio >= config.strategy.min_volume_ratio},
            {"name": "atr_pct", "value": round(safe_float(row.get("atr_pct")), 6), "passed": _volatility_ok(row)},
            {"name": "distance_to_ema_mid", "value": round(close - ema_mid, 6), "passed": side != "flat"},
        ],
        "risk_formula": {
            "stop_atr_mult": config.strategy.stop_atr_mult,
            "reward_risk": config.strategy.reward_risk,
            "fee_bps": config.fee_bps,
            "slippage_bps": config.slippage_bps,
        },
        "reasons": reasons,
    }


def _volatility_ok(row: pd.Series) -> bool:
    atr_pct = safe_float(row.get("atr_pct"))
    return 0.001 <= atr_pct <= 0.02


def _mode_sync_healthy(config: AppConfig, mode: str) -> bool:
    if mode == "paper":
        return True
    if not _mode_self_check_healthy(config, mode):
        return False
    sync = latest_exchange_sync_summary(
        config.db_path,
        mode,
        max_age_seconds=config.exchange_sync_max_age_seconds,
    )
    return bool(sync and sync.get("passed") and sync.get("is_fresh"))


def _mode_self_check_healthy(config: AppConfig, mode: str) -> bool:
    if mode == "paper":
        return True
    self_check = latest_exchange_self_check_summary(
        config.db_path,
        mode,
        max_age_seconds=config.exchange_self_check_max_age_seconds,
    )
    return bool(self_check and self_check.get("passed") and self_check.get("is_fresh"))


def _draft_id(symbol: str, bar_time: str, side: str) -> str:
    raw = f"{symbol}:{bar_time}:{side}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _signal_window(config: AppConfig) -> int:
    strategy = config.strategy
    indicator_need = max(
        strategy.ema_slow,
        strategy.htf_ema_slow * strategy.trend_timeframe_bars,
        strategy.regime_lookback,
        strategy.channel_lookback,
        strategy.volatility_lookback,
        strategy.volume_period,
        strategy.breakout_lookback,
    )
    return max(indicator_need + 300, 1200)
