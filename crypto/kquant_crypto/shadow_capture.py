from __future__ import annotations

"""Capture EVAL-approved observations without creating synthetic shadow days."""

from pathlib import Path
from typing import Any, Mapping

from .evaluation_store import get_trade_plan, latest_evaluations
from .shadow_store import save_shadow_observation


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def shadow_payload_from_evaluation(
    evaluation: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the immutable observation payload from two persisted records.

    This function intentionally does not choose defaults for point-in-time
    fields. A missing cutoff or coverage value is a data-quality failure, not a
    reason to manufacture a valid observation.
    """

    if not bool(evaluation.get("allowed_shadow")):
        raise ValueError("evaluation is not shadow eligible")
    evaluation_id = _required_text(evaluation.get("evaluation_id"), "evaluation_id")
    as_of_time = _required_text(evaluation.get("evaluated_at"), "as_of_time")
    plan_payload = plan.get("payload") if isinstance(plan.get("payload"), Mapping) else {}
    data_cutoff_time = _required_text(
        plan.get("data_cutoff_time") or plan_payload.get("data_cutoff_time"),
        "data_cutoff_time",
    )
    asset_id = _required_text(evaluation.get("asset_id") or plan.get("asset_id"), "asset_id")
    symbol = _required_text(evaluation.get("symbol") or plan.get("symbol"), "symbol").upper()
    strategy_version = _required_text(
        evaluation.get("strategy_version") or plan.get("strategy_version"),
        "strategy_version",
    )
    action = _required_text(
        plan.get("action") or plan_payload.get("action") or plan.get("proposed_action") or evaluation.get("strategy_stage"),
        "action",
    )
    coverage_value = plan.get("coverage", plan_payload.get("coverage"))
    if coverage_value is None:
        raise ValueError("coverage is required")
    try:
        coverage = float(coverage_value)
    except (TypeError, ValueError) as exc:
        raise ValueError("coverage must be numeric") from exc
    if not 0.0 <= coverage <= 1.0:
        raise ValueError("coverage must be between 0 and 1")

    return {
        "asset_scope": "crypto",
        "asset_id": asset_id,
        "symbol": symbol,
        "strategy_version": strategy_version,
        "action": action,
        "strategy_stage": str(evaluation.get("strategy_stage") or plan.get("proposed_stage") or "UNKNOWN"),
        "as_of_time": as_of_time,
        "data_cutoff_time": data_cutoff_time,
        "source_status": str(plan.get("data_quality_status") or "unknown").lower(),
        "coverage": coverage,
        "hard_veto": bool(plan.get("hard_veto")),
        "feature_snapshot_id": str(plan.get("feature_snapshot_id") or plan_payload.get("feature_snapshot_id") or ""),
        "model_version": str(plan.get("model_version") or plan_payload.get("model_version") or ""),
        "factor_snapshot_hash": str(evaluation.get("factor_snapshot_hash") or plan.get("factor_snapshot_hash") or ""),
        "source_snapshot_ids": list(evaluation.get("source_snapshot_ids") or plan.get("source_snapshot_ids") or []),
        "entry_zone": list(evaluation.get("entry_zone") or plan.get("entry_zone") or []),
        "stop_zone": list(evaluation.get("stop_zone") or plan.get("stop_zone") or []),
        "target_zone": list(evaluation.get("target_zone") or plan.get("target_zone") or []),
        "bayesian": dict(plan.get("bayesian") or plan_payload.get("bayesian") or {}),
        "monte_carlo": dict(plan.get("monte_carlo") or plan_payload.get("monte_carlo") or {}),
        "ai_rank": plan.get("ai_rank", plan_payload.get("ai_rank")),
        "evaluation_id": evaluation_id,
        "roll_id": str(plan.get("roll_id") or plan_payload.get("roll_id") or ""),
    }


def capture_shadow_observations(db_path: Path, *, limit: int = 200) -> dict[str, Any]:
    """Persist only currently EVAL-approved observations and report skips."""

    created = 0
    duplicates = 0
    skipped: list[dict[str, str]] = []
    eligible = 0
    for evaluation in latest_evaluations(db_path, limit=max(1, min(int(limit), 200))):
        if not bool(evaluation.get("allowed_shadow")):
            continue
        eligible += 1
        evaluation_id = str(evaluation.get("evaluation_id") or "unknown")
        try:
            plan_id = _required_text(evaluation.get("plan_id"), "plan_id")
            plan = get_trade_plan(db_path, plan_id)
            if plan is None:
                raise ValueError("trade plan not found")
            payload = shadow_payload_from_evaluation(evaluation, plan)
            _, was_created = save_shadow_observation(db_path, payload)
            if was_created:
                created += 1
            else:
                duplicates += 1
        except (TypeError, ValueError, KeyError) as exc:
            skipped.append({"evaluation_id": evaluation_id, "reason": str(exc)})
    return {
        "eligible_evaluations": eligible,
        "created": created,
        "duplicates": duplicates,
        "skipped": skipped,
        "synthetic_days_created": 0,
        "research_only": True,
    }


__all__ = ["capture_shadow_observations", "shadow_payload_from_evaluation"]
