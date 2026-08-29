from __future__ import annotations

from typing import Any


MAX_ACCOUNT_RISK_PCT = 0.5
MIN_AVERAGE_DOLLAR_VOLUME = 5_000_000.0
MAX_GAP_RISK_PCT = 2.5
MIN_RISK_REWARD = 2.0


def assess_trade_risk(
    *,
    daily_candles: list[dict[str, Any]],
    feature_values: dict[str, Any],
    entry_plan: dict[str, Any],
    stop_plan: dict[str, Any],
    risk_reward_plan: dict[str, Any],
    data_clean: bool,
) -> dict[str, Any]:
    """Assess a manual trade plan; never derive an order quantity or submit one."""
    entry_low = float(entry_plan.get("entry_low") or 0)
    entry_high = float(entry_plan.get("entry_high") or 0)
    stop = float(stop_plan.get("stop") or 0)
    entry_mid = (entry_low + entry_high) / 2 if entry_low > 0 and entry_high > 0 else 0
    risk_per_share = max(entry_mid - stop, 0.0)
    risk_pct = risk_per_share / entry_mid * 100 if entry_mid else None
    rr = float(risk_reward_plan.get("risk_reward_value") or 0)
    completed = [item for item in daily_candles if item.get("bar_state") != "forming_candle"]
    recent_lows = [float(item["low"]) for item in completed[-10:]]
    recent_swing_low = min(recent_lows) if recent_lows else None
    recent_volumes = [float(item.get("volume") or 0) for item in completed[-20:]]
    close = float(completed[-1]["close"]) if completed else 0.0
    average_dollar_volume = close * (sum(recent_volumes) / len(recent_volumes)) if recent_volumes and close else 0.0
    gap_risk = feature_values.get("gap_risk_pct")
    extension = feature_values.get("extension_pct")
    atr_pct = feature_values.get("atr_pct")
    hard_vetoes: list[str] = []
    warnings: list[str] = []
    if not data_clean:
        hard_vetoes.append("data_quality_not_clean")
    if not entry_mid or stop <= 0 or stop >= entry_mid:
        hard_vetoes.append("invalid_stop")
    if rr < MIN_RISK_REWARD:
        hard_vetoes.append("risk_reward_below_minimum")
    if average_dollar_volume < MIN_AVERAGE_DOLLAR_VOLUME:
        hard_vetoes.append("insufficient_liquidity")
    if gap_risk is not None and float(gap_risk) > MAX_GAP_RISK_PCT:
        warnings.append("elevated_gap_risk")
    if extension is not None and float(extension) > 5.5:
        warnings.append("extension_chase_risk")
    if atr_pct is not None and float(atr_pct) > 5.0:
        warnings.append("elevated_atr_risk")
    if recent_swing_low is not None and stop > recent_swing_low:
        warnings.append("stop_above_recent_swing_low")
    return {
        "status": "clear" if not hard_vetoes else "blocked",
        "eligible_for_manual_money_review": not hard_vetoes,
        "hard_vetoes": hard_vetoes,
        "warnings": warnings,
        "entry_mid": round(entry_mid, 4) if entry_mid else None,
        "stop": round(stop, 4) if stop else None,
        "risk_per_share": round(risk_per_share, 4) if risk_per_share else None,
        "risk_pct_of_entry": round(risk_pct, 3) if risk_pct is not None else None,
        "risk_reward_value": round(rr, 3),
        "recent_swing_low": round(recent_swing_low, 4) if recent_swing_low is not None else None,
        "average_daily_dollar_volume": round(average_dollar_volume, 2),
        "gap_risk_pct": round(float(gap_risk), 3) if gap_risk is not None else None,
        "extension_pct": round(float(extension), 3) if extension is not None else None,
        "atr_pct": round(float(atr_pct), 3) if atr_pct is not None else None,
        "maximum_account_risk_pct": MAX_ACCOUNT_RISK_PCT,
        "position_sizing_requires_account_value": True,
        "no_order_submission": True,
    }
