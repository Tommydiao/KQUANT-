from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


EVAL_POLICY_VERSION = "crypto_eval_v1.0.2"
REQUIRED_SNAPSHOT_BINDINGS = (
    "market",
    "regime",
    "factor",
    "security",
    "liquidity",
    "derivative",
    "signal",
    "plan",
    "model",
    "universe",
    "eval_policy",
)
EVAL_DECISIONS = (
    "REJECTED",
    "WATCH_ONLY",
    "ARMED",
    "PAPER_REVIEW",
    "SHADOW_ELIGIBLE",
    "INVALIDATED",
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_now() -> str:
    return utc_now().isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def stable_hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


@dataclass(frozen=True)
class TradePlanDraft:
    """Immutable input contract for the deterministic EVAL Agent.

    The contract intentionally carries source and version identifiers instead
    of raw provider objects.  Later agents may add fields to ``payload`` but
    they cannot silently replace the snapshot identifiers used for review.
    """

    plan_id: str
    asset_id: str
    symbol: str
    asset_type: str
    strategy_version: str
    proposed_stage: str = "MONITORING"
    factor_snapshot_hash: str = ""
    source_snapshot_ids: tuple[str, ...] = field(default_factory=tuple)
    snapshot_bindings: dict[str, str] = field(default_factory=dict)
    identity_status: str = "unknown"
    data_quality_status: str = "unknown"
    security_status: str = "unknown"
    liquidity_status: str = "unknown"
    market_regime: str = "unknown"
    model_status: str = "unknown"
    entry_zone: tuple[Any, ...] = field(default_factory=tuple)
    stop_zone: tuple[Any, ...] = field(default_factory=tuple)
    target_zone: tuple[Any, ...] = field(default_factory=tuple)
    risk_reward: float | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    invalid_conditions: tuple[Any, ...] = field(default_factory=tuple)
    factor_ids: tuple[str, ...] = field(default_factory=tuple)
    requested_execution_class: str = "research_only"
    material_state_hash: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=iso_now)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "TradePlanDraft":
        raw_bindings = value.get("snapshot_bindings") or {}
        bindings = {
            str(key): str(item)
            for key, item in raw_bindings.items()
            if str(key).strip() and str(item).strip()
        } if isinstance(raw_bindings, dict) else {}
        source_ids = tuple(str(item) for item in _list(value.get("source_snapshot_ids")) if str(item).strip())
        factor_ids = tuple(str(item) for item in _list(value.get("factor_ids")))
        payload = dict(value.get("payload") or {})
        identity = str(value.get("identity_status") or ("known" if value.get("asset_id") else "unknown"))
        draft = cls(
            plan_id=str(value.get("plan_id") or f"plan_{stable_hash(value)[:16]}"),
            asset_id=str(value.get("asset_id") or ""),
            symbol=str(value.get("symbol") or ""),
            asset_type=str(value.get("asset_type") or ""),
            strategy_version=str(value.get("strategy_version") or ""),
            proposed_stage=str(value.get("proposed_stage") or "MONITORING"),
            factor_snapshot_hash=str(value.get("factor_snapshot_hash") or ""),
            source_snapshot_ids=source_ids,
            snapshot_bindings=bindings,
            identity_status=identity,
            data_quality_status=str(value.get("data_quality_status") or "unknown"),
            security_status=str(value.get("security_status") or "unknown"),
            liquidity_status=str(value.get("liquidity_status") or "unknown"),
            market_regime=str(value.get("market_regime") or "unknown"),
            model_status=str(value.get("model_status") or "unknown"),
            entry_zone=tuple(_list(value.get("entry_zone"))),
            stop_zone=tuple(_list(value.get("stop_zone"))),
            target_zone=tuple(_list(value.get("target_zone"))),
            risk_reward=float(value["risk_reward"]) if value.get("risk_reward") is not None else None,
            valid_from=value.get("valid_from"),
            valid_until=value.get("valid_until"),
            invalid_conditions=tuple(_list(value.get("invalid_conditions"))),
            factor_ids=factor_ids,
            requested_execution_class=str(value.get("requested_execution_class") or "research_only"),
            material_state_hash=str(value.get("material_state_hash") or ""),
            payload=payload,
            created_at=str(value.get("created_at") or iso_now()),
        )
        if not draft.material_state_hash:
            object.__setattr__(draft, "material_state_hash", stable_hash({
                "asset_id": draft.asset_id,
                "strategy_version": draft.strategy_version,
                "factor_snapshot_hash": draft.factor_snapshot_hash,
                "entry_zone": draft.entry_zone,
                "stop_zone": draft.stop_zone,
                "target_zone": draft.target_zone,
                "valid_until": draft.valid_until,
            }))
        return draft

    def to_mapping(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "asset_id": self.asset_id,
            "symbol": self.symbol,
            "asset_type": self.asset_type,
            "strategy_version": self.strategy_version,
            "proposed_stage": self.proposed_stage,
            "factor_snapshot_hash": self.factor_snapshot_hash,
            "source_snapshot_ids": list(self.source_snapshot_ids),
            "snapshot_bindings": dict(self.snapshot_bindings),
            "identity_status": self.identity_status,
            "data_quality_status": self.data_quality_status,
            "security_status": self.security_status,
            "liquidity_status": self.liquidity_status,
            "market_regime": self.market_regime,
            "model_status": self.model_status,
            "entry_zone": list(self.entry_zone),
            "stop_zone": list(self.stop_zone),
            "target_zone": list(self.target_zone),
            "risk_reward": self.risk_reward,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "invalid_conditions": list(self.invalid_conditions),
            "factor_ids": list(self.factor_ids),
            "requested_execution_class": self.requested_execution_class,
            "material_state_hash": self.material_state_hash,
            "payload": self.payload,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class EvaluationDecision:
    evaluation_id: str
    plan_id: str
    asset_id: str
    symbol: str
    asset_type: str
    strategy_version: str
    decision: str
    evaluation_status: str
    execution_class: str
    allowed_alert: bool
    allowed_paper: bool
    allowed_shadow: bool
    evidence_grade: str
    strategy_stage: str
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
    evaluation_policy_version: str
    expires_at: str | None
    evaluated_at: str
    material_state_hash: str
    llm_participated: bool = False

    def to_mapping(self) -> dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "plan_id": self.plan_id,
            "asset_id": self.asset_id,
            "symbol": self.symbol,
            "asset_type": self.asset_type,
            "strategy_version": self.strategy_version,
            "decision": self.decision,
            "evaluation_status": self.evaluation_status,
            "execution_class": self.execution_class,
            "allowed_alert": self.allowed_alert,
            "allowed_paper": self.allowed_paper,
            "allowed_shadow": self.allowed_shadow,
            "evidence_grade": self.evidence_grade,
            "strategy_stage": self.strategy_stage,
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
            "evaluation_policy_version": self.evaluation_policy_version,
            "expires_at": self.expires_at,
            "evaluated_at": self.evaluated_at,
            "material_state_hash": self.material_state_hash,
            "llm_participated": self.llm_participated,
        }
