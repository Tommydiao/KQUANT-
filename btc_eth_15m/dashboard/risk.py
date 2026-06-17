from __future__ import annotations

import math

from btc_eth_15m.config import AppConfig
from btc_eth_15m.dashboard.models import LeverageDecision, RiskGate


def safe_float(value, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(parsed) or math.isinf(parsed):
        return default
    return parsed


def confidence_from_row(row) -> tuple[float, list[str]]:
    signal = int(getattr(row, "signal", 0))
    if signal == 0:
        return 0.0, ["no active directional signal"]

    score = 0.52
    reasons = ["directional signal passed"]
    volume = safe_float(getattr(row, "volume", None))
    volume_sma = safe_float(getattr(row, "volume_sma", None))
    close = safe_float(getattr(row, "close", None))
    atr_pct = safe_float(getattr(row, "atr_pct", None))
    regime_atr_pct = safe_float(getattr(row, "regime_atr_pct", None))
    rsi = safe_float(getattr(row, "rsi", None))
    htf_fast = safe_float(getattr(row, "htf_ema_fast", None))
    htf_slow = safe_float(getattr(row, "htf_ema_slow", None))

    if volume_sma > 0 and volume >= volume_sma:
        score += 0.10
        reasons.append("volume is above its moving average")
    elif volume_sma > 0 and volume >= volume_sma * 0.8:
        score += 0.05
        reasons.append("volume is acceptable")

    if close > 0 and htf_fast > 0 and htf_slow > 0:
        gap_bps = abs(htf_fast - htf_slow) / close * 10_000
        if gap_bps >= 15:
            score += 0.10
            reasons.append("higher-timeframe trend gap is strong")
        elif gap_bps >= 5:
            score += 0.05
            reasons.append("higher-timeframe trend gap is present")

    if 0.0015 <= atr_pct <= 0.012:
        score += 0.08
        reasons.append("15m volatility is inside the preferred band")
    if 0.0015 <= regime_atr_pct <= 0.015:
        score += 0.06
        reasons.append("regime volatility gate is inside range")

    if signal == 1 and 45 <= rsi <= 65:
        score += 0.07
        reasons.append("long RSI is in the preferred band")
    elif signal == -1 and 35 <= rsi <= 55:
        score += 0.07
        reasons.append("short RSI is in the preferred band")

    return min(score, 0.95), reasons


def leverage_from_confidence(
    confidence: float,
    *,
    volatility_ok: bool,
    drawdown_ok: bool,
    order_sync_ok: bool,
    position_sync_ok: bool,
    min_leverage: int,
    max_leverage: int,
) -> LeverageDecision:
    reasons: list[str] = []
    if confidence < 0.60:
        leverage = 7
        reasons.append("confidence below 0.60 uses the minimum execution tier")
    elif confidence < 0.75:
        leverage = 10
        reasons.append("confidence between 0.60 and 0.75 uses the 10x tier")
    elif confidence < 0.85:
        leverage = 12
        reasons.append("confidence between 0.75 and 0.85 uses the 12x tier")
    else:
        leverage = 15
        reasons.append("confidence above 0.85 requests the highest tier")

    high_tier_blockers = []
    if not volatility_ok:
        high_tier_blockers.append("volatility gate")
    if not drawdown_ok:
        high_tier_blockers.append("drawdown gate")
    if not order_sync_ok:
        high_tier_blockers.append("order sync gate")
    if not position_sync_ok:
        high_tier_blockers.append("position sync gate")
    if leverage == 15 and high_tier_blockers:
        leverage = 12
        reasons.append("15x was reduced because " + ", ".join(high_tier_blockers) + " did not pass")

    leverage = max(min_leverage, min(leverage, max_leverage))
    return LeverageDecision(
        leverage=leverage,
        confidence=round(confidence, 4),
        max_allowed_leverage=max_leverage,
        reasons=reasons,
    )


def risk_gates(
    config: AppConfig,
    *,
    mode: str,
    kill_switch: bool,
    order_sync_ok: bool,
    position_sync_ok: bool,
    market_data_ok: bool,
    api_error_ok: bool,
    rate_limit_ok: bool,
    open_margin_usdt: float,
    daily_margin_used_usdt: float,
    daily_loss_used_usdt: float,
    exchange_self_check_ok: bool | None = None,
    symbol_open_positions: int | None = None,
) -> list[RiskGate]:
    max_daily_loss_usdt = config.initial_equity * config.max_daily_loss
    gates = [
        RiskGate("kill_switch", not kill_switch, "Kill switch is off." if not kill_switch else "Kill switch is active."),
        RiskGate("market_data", market_data_ok, "Market data is fresh." if market_data_ok else "Market data is stale or missing."),
        RiskGate("api_errors", api_error_ok, "No blocking API error." if api_error_ok else "API error is blocking execution."),
        RiskGate("rate_limit", rate_limit_ok, "Rate limit budget is healthy." if rate_limit_ok else "Rate limit protection is active."),
        RiskGate(
            "open_margin_cap",
            open_margin_usdt <= config.live_margin_cap_usdt,
            f"Open margin {open_margin_usdt:.2f} / {config.live_margin_cap_usdt:.2f} USDT.",
        ),
        RiskGate(
            "open_margin_budget",
            open_margin_usdt < config.live_margin_cap_usdt,
            (
                f"Open margin budget has room: {open_margin_usdt:.2f} / {config.live_margin_cap_usdt:.2f} USDT."
                if open_margin_usdt < config.live_margin_cap_usdt
                else f"Open margin budget is exhausted: {open_margin_usdt:.2f} / {config.live_margin_cap_usdt:.2f} USDT."
            ),
        ),
        RiskGate(
            "daily_margin_cap",
            daily_margin_used_usdt <= config.live_daily_margin_cap_usdt,
            f"Daily margin {daily_margin_used_usdt:.2f} / {config.live_daily_margin_cap_usdt:.2f} USDT.",
        ),
        RiskGate(
            "daily_margin_budget",
            daily_margin_used_usdt < config.live_daily_margin_cap_usdt,
            (
                f"Daily margin budget has room: {daily_margin_used_usdt:.2f} / {config.live_daily_margin_cap_usdt:.2f} USDT."
                if daily_margin_used_usdt < config.live_daily_margin_cap_usdt
                else f"Daily margin budget is exhausted: {daily_margin_used_usdt:.2f} / {config.live_daily_margin_cap_usdt:.2f} USDT."
            ),
        ),
        RiskGate(
            "daily_loss_cap",
            daily_loss_within_cap(daily_loss_used_usdt, max_daily_loss_usdt),
            f"Daily realized loss {daily_loss_used_usdt:.2f} / {max_daily_loss_usdt:.2f} USDT.",
        ),
    ]
    if exchange_self_check_ok is not None:
        gates.insert(
            1,
            RiskGate(
                "exchange_self_check",
                exchange_self_check_ok,
                (
                    "Exchange self-check is healthy."
                    if exchange_self_check_ok
                    else "Exchange self-check is not healthy."
                ),
            ),
        )
    gates.insert(
        2 if exchange_self_check_ok is not None else 1,
        RiskGate("order_sync", order_sync_ok, "Order sync is healthy." if order_sync_ok else "Order sync is not healthy."),
    )
    gates.insert(
        3 if exchange_self_check_ok is not None else 2,
        RiskGate(
            "position_sync",
            position_sync_ok,
            "Position sync is healthy." if position_sync_ok else "Position sync is not healthy.",
        ),
    )
    if symbol_open_positions is not None:
        gates.append(
            RiskGate(
                "position_count_cap",
                symbol_open_positions < config.max_positions_per_symbol,
                f"Open positions for this symbol {symbol_open_positions} / {config.max_positions_per_symbol}.",
            )
        )
    if mode == "live":
        gates.append(
            RiskGate(
                "live_enabled",
                bool(config.live_enabled),
                "Live trading is explicitly enabled." if config.live_enabled else "Live trading is locked by configuration.",
            )
        )
    return gates


def blocked_reasons(gates: list[RiskGate]) -> list[str]:
    return [gate.message for gate in gates if not gate.passed]


def daily_loss_within_cap(current_loss_usdt: float, max_daily_loss_usdt: float) -> bool:
    if max_daily_loss_usdt <= 0:
        return current_loss_usdt <= 0
    return current_loss_usdt < max_daily_loss_usdt
