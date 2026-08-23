from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class InstructionState(StrEnum):
    """Operational state of a research instruction, never an order state."""

    MONITORING = "MONITORING"
    READY = "READY"
    TRIGGERED = "TRIGGERED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    EXIT_REVIEW = "EXIT_REVIEW"


def state_from_evaluation(evaluation: dict[str, Any]) -> InstructionState:
    """Map the final EVAL decision to a conservative instruction state.

    A plan can only become TRIGGERED when EVAL explicitly authorizes an alert.
    The current foundation policy never does that, so its positive-looking
    decisions remain READY rather than being presented as actionable.
    """

    decision = str(evaluation.get("decision") or "WATCH_ONLY").upper()
    if decision == "INVALIDATED":
        return InstructionState.INVALIDATED
    if decision == "REJECTED":
        return InstructionState.INVALIDATED
    if evaluation.get("expires_at") and evaluation.get("expired"):
        return InstructionState.EXPIRED
    if decision in {"PAPER_REVIEW", "SHADOW_ELIGIBLE"} and bool(evaluation.get("allowed_alert")):
        return InstructionState.TRIGGERED
    if decision == "ARMED" or decision in {"PAPER_REVIEW", "SHADOW_ELIGIBLE"}:
        return InstructionState.READY
    return InstructionState.MONITORING


@dataclass(frozen=True)
class TradeInstruction:
    instruction_id: str
    plan_id: str
    evaluation_id: str
    asset_id: str
    symbol: str
    asset_type: str
    strategy_version: str
    state: str
    evaluation_decision: str
    execution_class: str
    allowed_alert: bool
    allowed_paper: bool
    allowed_shadow: bool
    entry_zone: list[Any]
    stop_zone: list[Any]
    target_zone: list[Any]
    risk_reward: float | None
    supporting_factors: list[dict[str, Any]]
    opposing_factors: list[dict[str, Any]]
    blockers: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    source_snapshot_ids: list[str]
    snapshot_bindings: dict[str, str]
    factor_snapshot_hash: str
    material_state_hash: str
    evaluation_policy_version: str
    expires_at: str | None
    created_at: str
    updated_at: str

    def to_mapping(self) -> dict[str, Any]:
        return {
            "instruction_id": self.instruction_id,
            "plan_id": self.plan_id,
            "evaluation_id": self.evaluation_id,
            "asset_id": self.asset_id,
            "symbol": self.symbol,
            "asset_type": self.asset_type,
            "strategy_version": self.strategy_version,
            "state": self.state,
            "evaluation_decision": self.evaluation_decision,
            "execution_class": self.execution_class,
            "allowed_alert": self.allowed_alert,
            "allowed_paper": self.allowed_paper,
            "allowed_shadow": self.allowed_shadow,
            "entry_zone": self.entry_zone,
            "stop_zone": self.stop_zone,
            "target_zone": self.target_zone,
            "risk_reward": self.risk_reward,
            "supporting_factors": self.supporting_factors,
            "opposing_factors": self.opposing_factors,
            "blockers": self.blockers,
            "warnings": self.warnings,
            "source_snapshot_ids": self.source_snapshot_ids,
            "snapshot_bindings": self.snapshot_bindings,
            "factor_snapshot_hash": self.factor_snapshot_hash,
            "material_state_hash": self.material_state_hash,
            "evaluation_policy_version": self.evaluation_policy_version,
            "expires_at": self.expires_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def instruction_from_evaluation(evaluation: dict[str, Any], *, now: str) -> TradeInstruction:
    """Build an auditable instruction projection from an EVAL result."""

    state = state_from_evaluation(evaluation)
    return TradeInstruction(
        instruction_id=f"instruction_{evaluation.get('evaluation_id') or evaluation.get('plan_id')}",
        plan_id=str(evaluation.get("plan_id") or ""),
        evaluation_id=str(evaluation.get("evaluation_id") or ""),
        asset_id=str(evaluation.get("asset_id") or ""),
        symbol=str(evaluation.get("symbol") or ""),
        asset_type=str(evaluation.get("asset_type") or ""),
        strategy_version=str(evaluation.get("strategy_version") or ""),
        state=state.value,
        evaluation_decision=str(evaluation.get("decision") or "WATCH_ONLY"),
        execution_class=str(evaluation.get("execution_class") or "research_only"),
        allowed_alert=bool(evaluation.get("allowed_alert")),
        allowed_paper=bool(evaluation.get("allowed_paper")),
        allowed_shadow=bool(evaluation.get("allowed_shadow")),
        entry_zone=list(evaluation.get("entry_zone") or []),
        stop_zone=list(evaluation.get("stop_zone") or []),
        target_zone=list(evaluation.get("target_zone") or []),
        risk_reward=evaluation.get("risk_reward"),
        supporting_factors=list(evaluation.get("supporting_factors") or []),
        opposing_factors=list(evaluation.get("opposing_factors") or []),
        blockers=list(evaluation.get("blockers") or []),
        warnings=list(evaluation.get("warnings") or []),
        source_snapshot_ids=list(evaluation.get("source_snapshot_ids") or []),
        snapshot_bindings=dict(evaluation.get("snapshot_bindings") or {}),
        factor_snapshot_hash=str(evaluation.get("factor_snapshot_hash") or ""),
        material_state_hash=str(evaluation.get("material_state_hash") or ""),
        evaluation_policy_version=str(evaluation.get("evaluation_policy_version") or ""),
        expires_at=evaluation.get("expires_at"),
        created_at=now,
        updated_at=now,
    )
