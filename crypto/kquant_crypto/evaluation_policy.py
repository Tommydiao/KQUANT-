from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .evaluation_models import (
    EVAL_POLICY_VERSION,
    REQUIRED_SNAPSHOT_BINDINGS,
    EvaluationDecision,
    TradePlanDraft,
    iso_now,
)
from .calibration import model_evidence_gate
from .model_evidence import verify_model_evidence_packet
from .universe_catalog import candidate_instrument


BLOCK_PRIORITY = {
    "security": 10,
    "data": 20,
    "liquidity": 30,
    "market_regime": 40,
    "model_evidence": 50,
    "trade_plan": 60,
    "duplicate_or_expiry": 70,
}

REGISTERED_FACTOR_IDS = frozenset()


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _block(group: str, code: str, message: str, *, severity: str = "block", details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "blocker_group": group,
        "code": code,
        "severity": severity,
        "message": message,
        "details": details or {},
    }


def evaluate_plan(
    draft: TradePlanDraft,
    *,
    previous_decision: dict[str, Any] | None = None,
    now: datetime | None = None,
    registered_factor_ids: frozenset[str] = REGISTERED_FACTOR_IDS,
    allow_alert: bool = False,
    allow_paper: bool = False,
    allow_shadow: bool = False,
) -> EvaluationDecision:
    """Run the Week 1 deterministic EVAL policy.

    This function is deliberately conservative: the foundation release can
    create auditable research observations, but cannot authorize alerts,
    Paper or Shadow.  Later weeks may widen a gate only through a new policy
    version and tests.
    """

    evaluated_at = (now or datetime.now(UTC)).isoformat()
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    if not draft.asset_id or not draft.symbol or not draft.asset_type or not draft.strategy_version:
        blockers.append(_block("security", "asset_identity_unknown", "标的唯一身份或策略版本不完整。"))
    if draft.identity_status.lower() not in {"known", "verified", "pass", "available"}:
        blockers.append(_block("security", "asset_identity_unverified", "标的身份尚未完成唯一性确认。"))

    security = draft.security_status.lower()
    if security in {"unknown", "", "unavailable", "pending"}:
        blockers.append(_block("security", "security_snapshot_unknown", "安全快照未知，禁止进入 Paper 或 Shadow。"))
    # Provider availability is not a security decision. Only an explicit,
    # completed safety assessment may satisfy the security gate.
    elif security not in {"pass", "passed", "safe"}:
        blockers.append(_block("security", "security_blocked", "安全检查未通过。", details={"status": draft.security_status}))

    data_quality = draft.data_quality_status.lower()
    if data_quality not in {"live", "available", "fresh", "passed"}:
        blockers.append(_block("data", "data_not_ready", "行情数据不够新鲜或不完整。", details={"status": draft.data_quality_status}))
    if draft.payload.get("forming_candle") or draft.payload.get("forming_bar"):
        blockers.append(_block("data", "forming_candle_not_eligible", "形成中的 K 线只能展示，不能通过 EVAL。"))
    if draft.payload.get("cross_source_conflict"):
        blockers.append(_block("data", "cross_source_conflict", "跨来源行情存在冲突，暂不能形成审核结论。"))
    provider_status = str(draft.payload.get("provider_status") or "").lower()
    if provider_status in {"stale", "disconnected", "resync_required", "provider_unavailable"}:
        blockers.append(_block("data", "provider_not_ready", "行情 provider 尚未恢复到可信状态。", details={"status": provider_status}))

    if draft.payload.get("clock_skew") or draft.payload.get("provider_clock_skew"):
        blockers.append(_block("data", "provider_clock_skew", "Provider clock calibration is not trustworthy."))
    if draft.payload.get("event_risk_blocked") or draft.payload.get("corporate_event_risk"):
        blockers.append(_block("data", "event_risk_blocked", "Event-risk review is incomplete."))

    binding_keys = set(draft.snapshot_bindings)
    missing_bindings = [key for key in REQUIRED_SNAPSHOT_BINDINGS if not draft.snapshot_bindings.get(key)]
    unknown_bindings = sorted(binding_keys - set(REQUIRED_SNAPSHOT_BINDINGS))
    if missing_bindings:
        blockers.append(_block(
            "data",
            "snapshot_binding_incomplete",
            "评估缺少完整的行情、状态、因子、安全、流动性、信号和版本快照绑定。",
            details={"missing": missing_bindings},
        ))
    if unknown_bindings:
        blockers.append(_block(
            "model_evidence",
            "snapshot_binding_unknown",
            "评估包含未注册的快照绑定类型。",
            details={"unknown": unknown_bindings},
        ))
    if draft.snapshot_bindings.get("factor") and draft.factor_snapshot_hash and draft.snapshot_bindings["factor"] != draft.factor_snapshot_hash:
        blockers.append(_block(
            "model_evidence",
            "factor_snapshot_mismatch",
            "因子快照绑定与因子哈希不一致。",
            details={"binding": draft.snapshot_bindings["factor"], "factor_snapshot_hash": draft.factor_snapshot_hash},
        ))
    if draft.snapshot_bindings.get("plan") and draft.snapshot_bindings["plan"] != draft.plan_id:
        blockers.append(_block(
            "trade_plan",
            "plan_snapshot_mismatch",
            "交易计划快照绑定与计划 ID 不一致。",
        ))
    if draft.snapshot_bindings.get("eval_policy") and draft.snapshot_bindings["eval_policy"] != EVAL_POLICY_VERSION:
        blockers.append(_block(
            "model_evidence",
            "eval_policy_version_mismatch",
            "EVAL 策略版本与当前运行版本不一致。",
            details={"bound": draft.snapshot_bindings["eval_policy"], "current": EVAL_POLICY_VERSION},
        ))

    liquidity = draft.liquidity_status.lower()
    if liquidity not in {"pass", "passed", "available", "live", "fresh"}:
        blockers.append(_block("liquidity", "liquidity_not_ready", "流动性或成交成本尚未满足要求。", details={"status": draft.liquidity_status}))

    if draft.payload.get("bbo_valid") is False or draft.payload.get("depth_status") in {"unavailable", "unknown", "stale"}:
        blockers.append(_block("liquidity", "bbo_unavailable", "BBO or depth is unavailable."))
    spread_bps = draft.payload.get("spread_bps")
    if spread_bps is not None:
        try:
            if float(spread_bps) > float(draft.payload.get("max_spread_bps", 80.0)):
                blockers.append(_block("liquidity", "spread_too_wide", "Spread exceeds the execution limit.", details={"spread_bps": spread_bps}))
        except (TypeError, ValueError):
            blockers.append(_block("liquidity", "spread_invalid", "Spread is not numeric."))
    price_impact_bps = draft.payload.get("estimated_price_impact_bps")
    if price_impact_bps is not None:
        try:
            if float(price_impact_bps) > float(draft.payload.get("max_price_impact_bps", 150.0)):
                blockers.append(_block("liquidity", "price_impact_too_high", "Estimated price impact exceeds the limit.", details={"estimated_price_impact_bps": price_impact_bps}))
        except (TypeError, ValueError):
            blockers.append(_block("liquidity", "price_impact_invalid", "Estimated price impact is not numeric."))
    for field, code, limit in (("buy_tax", "buy_tax_too_high", 0.10), ("sell_tax", "sell_tax_too_high", 0.10)):
        value = draft.payload.get(field)
        if value is not None:
            try:
                if float(value) > limit:
                    blockers.append(_block("liquidity", code, "Token tax exceeds the safety limit.", details={field: value}))
            except (TypeError, ValueError):
                blockers.append(_block("liquidity", f"{field}_invalid", "Token tax is not numeric."))
    funding = draft.payload.get("funding_rate")
    if funding is not None:
        try:
            if abs(float(funding)) > float(draft.payload.get("max_abs_funding", 0.01)):
                blockers.append(_block("liquidity", "funding_extreme", "Funding is outside the policy range.", details={"funding_rate": funding}))
        except (TypeError, ValueError):
            blockers.append(_block("liquidity", "funding_invalid", "Funding is not numeric."))
    oi_change = draft.payload.get("oi_change")
    if oi_change is not None:
        try:
            if float(oi_change) <= float(draft.payload.get("min_oi_change", -0.25)):
                blockers.append(_block("liquidity", "oi_deleveraging", "Open interest is rapidly deleveraging.", details={"oi_change": oi_change}))
        except (TypeError, ValueError):
            blockers.append(_block("liquidity", "oi_invalid", "Open interest change is not numeric."))
    if draft.payload.get("lp_status") in {"removed", "withdrawn", "unknown", "unverified"}:
        blockers.append(_block("liquidity", "lp_not_safe", "DEX liquidity-pool status is not verified.", details={"lp_status": draft.payload.get("lp_status")}))

    if draft.market_regime.lower() in {"unknown", "", "data_caution", "deleveraging", "liquidity_stress"}:
        blockers.append(_block("market_regime", "market_regime_blocked", "当前市场状态不允许启动类计划。", details={"regime": draft.market_regime}))

    unknown_factors = sorted(set(draft.factor_ids) - set(registered_factor_ids))
    if unknown_factors or not draft.factor_snapshot_hash:
        blockers.append(_block(
            "model_evidence",
            "factor_registry_mismatch",
            "因子快照缺失或包含未注册因子。",
            details={"unknown_factor_ids": unknown_factors},
        ))
    if draft.model_status.lower() not in {"passed", "validated", "available"}:
        blockers.append(_block("model_evidence", "model_gate_closed", "模型证据尚未通过当前版本 Gate。", details={"status": draft.model_status}))

    expected_model_version = draft.payload.get("expected_model_version")
    if expected_model_version and draft.payload.get("model_version") != expected_model_version:
        blockers.append(_block("model_evidence", "model_version_mismatch", "Model version does not match the validated version.", details={"model_version": draft.payload.get("model_version"), "expected_model_version": expected_model_version}))
    if draft.payload.get("test_partition_locked") is False or draft.payload.get("dataset_hash_mismatch"):
        blockers.append(_block("model_evidence", "dataset_integrity_failed", "Validation dataset integrity check failed."))
    model_allowed, model_reasons = model_evidence_gate(draft.payload)
    for reason in model_reasons:
        code = "model_calibration_gate_closed" if reason == "calibration_gate_closed" else reason
        if not any(item["code"] == code for item in blockers):
            blockers.append(_block("model_evidence", code, "模型概率或制品证据未通过当前 Gate。"))

    candidate = candidate_instrument(draft.symbol)
    if candidate is not None:
        packet = draft.payload.get("model_evidence_packet")
        if not isinstance(packet, dict):
            blockers.append(_block(
                "model_evidence",
                "model_evidence_packet_missing",
                "Candidate assets require a versioned mathematical evidence packet.",
            ))
        else:
            packet_market = str(packet.get("market_type") or "").lower()
            packet_asset = str(packet.get("asset_id") or "")
            if (
                packet_asset != draft.asset_id
                or packet_asset != candidate.asset_id
                or str(packet.get("symbol") or "").upper() != candidate.symbol
                or packet_market != candidate.market_type
            ):
                blockers.append(_block(
                    "model_evidence", "model_evidence_instrument_mismatch",
                    "The evidence packet does not match the candidate instrument.",
                ))
            if str(packet.get("strategy_version") or "") != draft.strategy_version:
                blockers.append(_block(
                    "model_evidence", "model_evidence_strategy_mismatch",
                    "The evidence packet strategy version does not match the trade plan.",
                ))
            if not packet.get("content_hash") or packet.get("promotion_status") not in {"SHADOW_ELIGIBLE", "TESTNET_CANDIDATE", "TESTNET_ENABLED"}:
                blockers.append(_block(
                    "model_evidence", "model_evidence_promotion_closed",
                    "Mathematical evidence is incomplete, uncalibrated or still limited-history.",
                    details={"packet_blockers": list(packet.get("blockers") or [])},
                ))
            packet_valid, packet_issues = verify_model_evidence_packet(packet)
            if not packet_valid:
                blockers.append(_block(
                    "model_evidence", "model_evidence_integrity_failed",
                    "The mathematical evidence packet failed its integrity check.",
                    details={"issues": list(packet_issues)},
                ))
            if draft.payload.get("model_evidence_persisted") is not True:
                blockers.append(_block(
                    "model_evidence", "model_evidence_not_persisted",
                    "The mathematical evidence packet is not bound to the audit database.",
                ))
        requested_risk = draft.payload.get("requested_risk_fraction")
        if requested_risk is not None:
            try:
                if float(requested_risk) > candidate.risk_fraction_cap:
                    blockers.append(_block(
                        "trade_plan", "candidate_risk_cap_exceeded",
                        "The requested risk exceeds the candidate asset cap.",
                        details={"requested": requested_risk, "maximum": candidate.risk_fraction_cap},
                    ))
            except (TypeError, ValueError):
                blockers.append(_block("trade_plan", "candidate_risk_fraction_invalid", "Candidate risk fraction is invalid."))

    missing_plan_fields = []
    if not draft.entry_zone:
        missing_plan_fields.append("entry_zone")
    if not draft.stop_zone:
        missing_plan_fields.append("stop_zone")
    if not draft.target_zone:
        missing_plan_fields.append("target_zone")
    if not draft.invalid_conditions:
        missing_plan_fields.append("invalid_conditions")
    if not draft.valid_until:
        missing_plan_fields.append("valid_until")
    if draft.risk_reward is None:
        missing_plan_fields.append("risk_reward")
    if missing_plan_fields:
        blockers.append(_block("trade_plan", "trade_plan_incomplete", "交易计划缺少必要字段。", details={"missing": missing_plan_fields}))

    expiry = _parse_time(draft.valid_until)
    if draft.valid_until and expiry is None:
        blockers.append(_block("duplicate_or_expiry", "expiry_invalid", "计划有效期格式无效。"))
    elif expiry and expiry <= (now or datetime.now(UTC)).astimezone(UTC):
        blockers.append(_block("duplicate_or_expiry", "plan_expired", "交易计划已经过期。"))

    if previous_decision and previous_decision.get("material_state_hash") == draft.material_state_hash:
        blockers.append(_block("duplicate_or_expiry", "duplicate_material_state", "相同 material state 已经评估过。"))

    if draft.risk_reward is not None and draft.risk_reward < 1.0:
        blockers.append(_block("trade_plan", "risk_reward_too_low", "风险收益比低于基础研究门槛。"))

    if not allow_paper and draft.requested_execution_class in {"paper", "paper_only", "shadow", "shadow_eligible"}:
        warnings.append({"code": "foundation_execution_gate", "message": "第 1 周基础版本尚未开放 Paper 或 Shadow。"})

    blockers.sort(key=lambda item: BLOCK_PRIORITY.get(item["blocker_group"], 999))
    decision = "WATCH_ONLY"
    if any(item["blocker_group"] == "security" for item in blockers):
        decision = "REJECTED"
    elif any(item["code"] == "plan_expired" for item in blockers):
        decision = "INVALIDATED"

    if not blockers and not allow_alert and not allow_paper and not allow_shadow:
        warnings.append({"code": "foundation_gate_closed", "message": "基础版本只允许研究观察，不允许 Paper 或 Shadow。"})
    if not blockers and allow_paper:
        decision = "PAPER_REVIEW"
    if not blockers and allow_shadow:
        decision = "SHADOW_ELIGIBLE"

    if not blockers and not allow_paper and not allow_shadow:
        proposed = str(draft.proposed_stage or "").upper()
        if proposed in {"ARMED", "BUY_REVIEW"}:
            decision = "ARMED"

    # Alert authority is an explicit release flag, never an inference from a
    # strategy stage. The default is closed until its evidence gate is passed.
    alert_allowed = (
        not blockers
        and allow_alert
        and decision in {"ARMED", "PAPER_REVIEW", "SHADOW_ELIGIBLE"}
    )
    downstream_allowed = bool(
        alert_allowed
        or (decision == "PAPER_REVIEW" and allow_paper)
        or (decision == "SHADOW_ELIGIBLE" and allow_shadow)
    )

    blocking_evidence = [item for item in blockers if item["severity"] == "block"]
    evidence_grade = "insufficient" if blocking_evidence else "limited"
    evaluation_status = "blocked" if blockers else ("passed" if downstream_allowed else "passed_with_warnings")
    if decision in {"REJECTED", "INVALIDATED"}:
        evaluation_status = "rejected"

    return EvaluationDecision(
        evaluation_id=f"eva_{uuid4().hex}",
        plan_id=draft.plan_id,
        asset_id=draft.asset_id,
        symbol=draft.symbol,
        asset_type=draft.asset_type,
        strategy_version=draft.strategy_version,
        decision=decision,
        evaluation_status=evaluation_status,
        execution_class="research_only" if decision in {"REJECTED", "WATCH_ONLY", "INVALIDATED"} else draft.requested_execution_class,
        allowed_alert=alert_allowed,
        allowed_paper=decision == "PAPER_REVIEW" and allow_paper,
        allowed_shadow=decision == "SHADOW_ELIGIBLE" and allow_shadow,
        evidence_grade=evidence_grade,
        strategy_stage=draft.proposed_stage,
        entry_zone=list(draft.entry_zone),
        stop_zone=list(draft.stop_zone),
        target_zone=list(draft.target_zone),
        risk_reward=draft.risk_reward,
        supporting_factors=list(draft.payload.get("supporting_factors") or []),
        opposing_factors=list(draft.payload.get("opposing_factors") or []),
        blockers=blockers,
        warnings=warnings,
        source_snapshot_ids=list(draft.source_snapshot_ids),
        snapshot_bindings=dict(draft.snapshot_bindings),
        factor_snapshot_hash=draft.factor_snapshot_hash,
        evaluation_policy_version=EVAL_POLICY_VERSION,
        expires_at=draft.valid_until,
        evaluated_at=evaluated_at,
        material_state_hash=draft.material_state_hash,
    )
