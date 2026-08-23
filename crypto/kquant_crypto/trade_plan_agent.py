from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from .evaluation_models import TradePlanDraft, stable_hash
from .signal_agent import SignalProposal


def build_trade_plan_draft(
    signal: SignalProposal,
    *,
    entry_zone: list[Any] | tuple[Any, ...],
    stop_zone: list[Any] | tuple[Any, ...],
    target_zone: list[Any] | tuple[Any, ...],
    risk_reward: float | None,
    source_snapshot_ids: list[str] | tuple[str, ...],
    factor_snapshot_hash: str,
    snapshot_bindings: dict[str, str] | None = None,
    valid_minutes: int = 60,
    invalid_conditions: list[str] | tuple[str, ...] = ("material_state_changed", "structure_failed", "data_stale"),
    model_status: str = "passed",
    requested_execution_class: str = "paper_only",
    as_of_time: str | None = None,
    plan_id: str | None = None,
) -> TradePlanDraft:
    """Translate a signal into an auditable draft; never into an order."""

    if as_of_time:
        parsed = datetime.fromisoformat(as_of_time.replace("Z", "+00:00"))
        now = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        now = now.astimezone(UTC)
    else:
        now = datetime.now(UTC)
    valid_until = now + timedelta(minutes=max(1, valid_minutes))
    payload = {
        "setup_score": signal.setup_score,
        "trigger_score": signal.trigger_score,
        "factor_version": signal.factor_version,
        "factor_values": signal.factor_values,
        "factor_contributions": signal.factor_contributions,
        "supporting_factors": list(signal.supporting_factors),
        "opposing_factors": list(signal.opposing_factors),
        "data_as_of": signal.as_of_time,
        "source": "deterministic_trade_plan_agent",
    }
    material_state_hash = stable_hash({
        "signal": signal.material_state_hash,
        "entry_zone": list(entry_zone),
        "stop_zone": list(stop_zone),
        "target_zone": list(target_zone),
        "valid_until": valid_until.isoformat(),
    })
    resolved_plan_id = plan_id or f"plan_{uuid4().hex}"
    bindings = dict(snapshot_bindings or {})
    bindings.setdefault("plan", resolved_plan_id)
    bindings.setdefault("factor", factor_snapshot_hash)
    return TradePlanDraft(
        plan_id=resolved_plan_id,
        asset_id=signal.asset_id,
        symbol=signal.symbol,
        asset_type=signal.asset_type,
        strategy_version=signal.strategy_version,
        proposed_stage=signal.stage,
        factor_snapshot_hash=factor_snapshot_hash,
        source_snapshot_ids=tuple(source_snapshot_ids),
        snapshot_bindings=bindings,
        identity_status="known",
        data_quality_status=signal.data_quality_status,
        security_status=signal.security_status,
        liquidity_status=signal.liquidity_status,
        market_regime=signal.market_regime,
        model_status=model_status,
        entry_zone=tuple(entry_zone),
        stop_zone=tuple(stop_zone),
        target_zone=tuple(target_zone),
        risk_reward=risk_reward,
        valid_from=now.isoformat(),
        valid_until=valid_until.isoformat(),
        invalid_conditions=tuple(invalid_conditions),
        factor_ids=tuple(signal.factor_values),
        requested_execution_class=requested_execution_class,
        material_state_hash=material_state_hash,
        payload=payload,
        created_at=now.isoformat(),
    )
