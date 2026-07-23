from __future__ import annotations

from typing import Any


HARD_VETO_POLICY_VERSION = "hard_veto_v1"


def evaluate_hard_veto(signal: dict[str, Any], market_regime: dict[str, Any] | None = None) -> dict[str, Any]:
    """Central no-buy gate. It is deterministic and cannot be overridden by AI."""
    data = dict(signal.get("data_status") or {})
    trade_risk = dict(signal.get("trade_risk_assessment") or {})
    historical = dict(signal.get("historical_edge") or {})
    features = dict(signal.get("features") or {})
    plans = dict(signal.get("risk_reward_plan") or {})
    regime = dict(market_regime or {})
    reasons: list[str] = []
    if data.get("data_quality") != "clean":
        reasons.append("data_quality_not_clean")
    if data.get("daily_provider_status") != "available" or data.get("hourly_provider_status") != "available":
        reasons.append("provider_not_available")
    if data.get("longbridge_required_for_buy") and not data.get("longbridge_live_data_clean"):
        reasons.append("primary_provider_not_longbridge")
    session = data.get("market_session") or data.get("session")
    if session in {"pre_market", "after_hours", "closed"}:
        reasons.append("session_not_regular")
    if regime.get("regime") in {"RISK_OFF", "DATA_CAUTION"}:
        reasons.append(f"market_regime_{str(regime.get('regime')).lower()}")
    reasons.extend(str(item) for item in trade_risk.get("hard_vetoes") or [])
    rr = float(plans.get("risk_reward_value") or 0)
    if rr < 2.0:
        reasons.append("risk_reward_below_minimum")
    if float(features.get("extension_pct") or 0) > 5.5:
        reasons.append("extension_too_high")
    if historical and int(historical.get("sample_count") or 0) < 10:
        reasons.append("insufficient_strategy_evidence")
    reasons = list(dict.fromkeys(reasons))
    return {
        "policy_version": HARD_VETO_POLICY_VERSION,
        "active": bool(reasons),
        "reasons": reasons,
        "buy_actions_allowed": not reasons,
        "ai_override_allowed": False,
    }
