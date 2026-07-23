from __future__ import annotations

import math
from typing import Any, Iterable


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_daily_candidate_board(signals: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Select a bounded, human-review queue from a completed signal scan."""

    normalized = [dict(signal) for signal in signals]

    def eligible(signal: dict[str, Any]) -> bool:
        return not bool((signal.get("hard_veto") or {}).get("active")) and (signal.get("data_status") or {}).get("data_quality") == "clean"

    def rank_key(signal: dict[str, Any]) -> tuple[float, float, str]:
        historical = signal.get("historical_edge") or {}
        return (
            -_number(signal.get("score")),
            -(_number(historical.get("focus_win_rate", historical.get("win_rate_5d"))) + _number(historical.get("focus_avg_return", historical.get("avg_forward_return_5d")))),
            str(signal.get("symbol") or ""),
        )

    buys = sorted((item for item in normalized if item.get("level") == "BUY SETUP" and eligible(item)), key=rank_key)[:3]
    watches = sorted((item for item in normalized if item.get("level") == "WATCH" and eligible(item)), key=rank_key)[:7]

    def compact(signal: dict[str, Any], rank: int, bucket: str) -> dict[str, Any]:
        conclusion = signal.get("trade_conclusion") or {}
        risk = signal.get("trade_risk_assessment") or {}
        stop = signal.get("stop_plan") or {}
        return {
            "rank": rank,
            "bucket": bucket,
            "symbol": signal.get("symbol"),
            "strategy_score": round(_number(signal.get("score")), 2),
            "ai_research_rank": None,
            "ai_research_status": "not_required_for_candidate_selection",
            "risk": {
                "status": risk.get("status"),
                "warnings": list(risk.get("warnings") or [])[:4],
                "hard_vetoes": list(risk.get("hard_vetoes") or [])[:4],
            },
            "data_status": (signal.get("data_status") or {}).get("data_quality"),
            "system_action": conclusion.get("action", "WAIT"),
            "invalidation": list(stop.get("invalidation") or [])[:4],
            "read_only_research": True,
        }

    return {
        "buy_setups": [compact(signal, index, "BUY SETUP") for index, signal in enumerate(buys, start=1)],
        "watch": [compact(signal, index, "WATCH") for index, signal in enumerate(watches, start=1)],
        "excluded_count": max(0, len(normalized) - len(buys) - len(watches)),
        "limits": {"buy_setups": 3, "watch": 7},
        "selection_policy": "clean data, no deterministic hard veto, then strategy score and historical edge",
        "read_only_research": True,
        "no_order_submission": True,
    }


def build_manual_trade_plan(signal: dict[str, Any]) -> dict[str, Any]:
    """Normalize an existing deterministic signal into a manual review plan."""

    entry = dict(signal.get("entry_plan") or {})
    stop = dict(signal.get("stop_plan") or {})
    target = dict(signal.get("target_plan") or {})
    risk_reward = dict(signal.get("risk_reward_plan") or {})
    hard_veto = dict(signal.get("hard_veto") or {})
    data_status = dict(signal.get("data_status") or {})
    blocked = bool(hard_veto.get("active")) or data_status.get("data_quality") != "clean"
    return {
        "symbol": signal.get("symbol"),
        "observe_price": (signal.get("features") or {}).get("close"),
        "entry_trigger": entry.get("trigger"),
        "entry_zone": entry.get("zone"),
        "entry_low": entry.get("entry_low"),
        "entry_high": entry.get("entry_high"),
        "stop": stop.get("stop"),
        "stop_basis": stop.get("basis"),
        "target_one": target.get("target_low"),
        "target_two": target.get("target_high"),
        "maximum_holding_period": signal.get("holding_period"),
        "invalidation": list(stop.get("invalidation") or []),
        "do_not_trade_reasons": list(hard_veto.get("reasons") or []) + list((signal.get("trade_risk_assessment") or {}).get("hard_vetoes") or []),
        "risk_reward": risk_reward.get("risk_reward"),
        "risk_reward_value": risk_reward.get("risk_reward_value"),
        "blocked": blocked,
        "manual_confirmation_required": True,
        "read_only_research": True,
        "no_order_submission": True,
    }


def calculate_manual_position_size(
    *,
    account_value: float,
    risk_per_trade_pct: float,
    entry_price: float,
    stop_price: float,
    max_total_risk_pct: float,
    currently_open_risk: float = 0.0,
    max_position_pct: float = 25.0,
) -> dict[str, Any]:
    """A local calculator for a human plan; it does not read an account."""

    account = _number(account_value)
    entry = _number(entry_price)
    stop = _number(stop_price)
    risk_pct = max(0.0, _number(risk_per_trade_pct))
    max_risk_pct = max(0.0, _number(max_total_risk_pct))
    open_risk = max(0.0, _number(currently_open_risk))
    if account <= 0 or entry <= 0 or stop <= 0 or stop >= entry:
        return {
            "valid": False,
            "reason": "account_value, entry_price, and a lower positive stop_price are required",
            "max_shares": 0,
            "read_only_research": True,
        }
    per_share_risk = entry - stop
    requested_risk = account * risk_pct / 100
    remaining_total_risk = max(0.0, account * max_risk_pct / 100 - open_risk)
    risk_budget = min(requested_risk, remaining_total_risk)
    share_by_risk = math.floor(risk_budget / per_share_risk)
    share_by_value = math.floor(account * max(0.0, _number(max_position_pct)) / 100 / entry)
    shares = max(0, min(share_by_risk, share_by_value))
    actual_risk = shares * per_share_risk
    notional = shares * entry
    return {
        "valid": shares > 0,
        "max_shares": shares,
        "risk_per_share": round(per_share_risk, 4),
        "requested_risk_dollars": round(requested_risk, 4),
        "remaining_total_risk_dollars": round(remaining_total_risk, 4),
        "actual_risk_dollars": round(actual_risk, 4),
        "position_notional": round(notional, 4),
        "position_pct_of_entered_account_value": round(notional / account * 100, 4),
        "exceeds_risk_limit": actual_risk > remaining_total_risk or actual_risk > requested_risk,
        "manual_input_only": True,
        "account_not_read_by_kquant": True,
        "no_order_submission": True,
    }
