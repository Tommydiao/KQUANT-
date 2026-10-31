from __future__ import annotations

from typing import Any


def build_today_workbench(
    *,
    run: dict[str, Any],
    market_regime: dict[str, Any] | None,
    market_data: dict[str, Any] | None,
    ai_status: dict[str, Any] | None,
    operational_health: dict[str, Any] | None,
    weekly_review: dict[str, Any] | None,
    production_readiness: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build the first-screen decision surface without inventing a trade signal."""

    candidates = dict(run.get("daily_candidates") or {})
    buy_setups = list(candidates.get("buy_setups") or [])[:3]
    watch = list(candidates.get("watch") or [])[:7]
    regime = dict(market_regime or run.get("market_regime") or {})
    market = dict(market_data or {})
    ai = dict(ai_status or {})
    operations = dict(operational_health or {})
    reasons: list[str] = []
    provider_status = str(run.get("provider_status") or market.get("status") or "unknown")
    if provider_status not in {"available", "healthy"}:
        reasons.append("Market data provider is not in an available state.")
    if int(run.get("provider_error_count") or 0) > 0:
        reasons.append("One or more provider errors are present in the latest scan.")
    if str(regime.get("regime") or "DATA_CAUTION") in {"RISK_OFF", "DATA_CAUTION"}:
        reasons.append(f"Market regime is {regime.get('regime') or 'DATA_CAUTION'}.")
    if operations.get("status") not in {None, "healthy"}:
        reasons.append("Operational health is not healthy.")
    if not buy_setups and not watch:
        reasons.append("No clean candidates are available for manual review.")
    if ai.get("status") not in {None, "available"}:
        reasons.append("AI is unavailable; deterministic research guardrails remain active.")
    no_trade = bool(reasons) or str((production_readiness or {}).get("decision") or "NO_GO") != "GO"
    if str((production_readiness or {}).get("decision") or "NO_GO") != "GO":
        reasons.append("Production readiness is not approved; use observation or paper simulation only.")
    decision = "NO_TRADE" if no_trade else "MANUAL_REVIEW"
    return {
        "decision": decision,
        "headline": "No trade" if decision == "NO_TRADE" else "Manual review only",
        "market": {
            "regime": regime.get("regime", "DATA_CAUTION"),
            "label": regime.get("label", "Data Caution"),
            "score": regime.get("score", 0),
            "session": regime.get("session", market.get("session", "unknown")),
        },
        "data_trust": {
            "provider_status": provider_status,
            "provider_error_count": int(run.get("provider_error_count") or 0),
            "source": run.get("cache_source") or market.get("default_source_type") or "unknown",
            "available": provider_status in {"available", "healthy"},
        },
        "top_candidates": buy_setups,
        "watch_candidates": watch,
        "risk": {
            "weekly_review": weekly_review or {},
            "production_decision": (production_readiness or {}).get("decision", "NO_GO"),
            "failed_gate_count": (production_readiness or {}).get("failed_gate_count", 0),
        },
        "exception_states": reasons,
        "diagnostics": {
            "ai_status": ai.get("status", "unknown"),
            "operational_status": operations.get("status", "unknown"),
            "scan_run_id": run.get("run_id"),
        },
        "read_only_research": True,
        "automatic_execution_allowed": False,
        "order_submission_enabled": False,
    }
