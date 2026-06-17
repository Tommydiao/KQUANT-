from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from btc_eth_15m.agent_harness.audit_log import AuditLogger
from btc_eth_15m.agent_harness.state_store import StateStore


HIGH_RISK_ACTIONS = {"live_order", "paper_to_live_promotion", "risk_override", "config_change"}


@dataclass(frozen=True)
class RiskConfig:
    live_trading_enabled: bool = False
    require_approval_for_live: bool = True
    max_order_notional: float = 100.0
    max_asset_exposure: float = 0.10
    max_daily_loss: float = 50.0
    audit_log_enabled: bool = True
    paper_trading_enabled: bool = True

    @classmethod
    def from_env(cls) -> "RiskConfig":
        return cls(
            live_trading_enabled=_env_bool("LIVE_TRADING_ENABLED", False),
            require_approval_for_live=_env_bool("REQUIRE_APPROVAL_FOR_LIVE", True),
            max_order_notional=_env_float("MAX_ORDER_NOTIONAL", 100.0),
            max_asset_exposure=_env_float("MAX_ASSET_EXPOSURE", 0.10),
            max_daily_loss=_env_float("MAX_DAILY_LOSS", 50.0),
            audit_log_enabled=_env_bool("AUDIT_LOG_ENABLED", True),
            paper_trading_enabled=_env_bool("PAPER_TRADING_ENABLED", True),
        )


class RiskManager:
    def __init__(self, store: StateStore, audit: AuditLogger, config: RiskConfig | None = None) -> None:
        self.store = store
        self.audit = audit
        self.config = config or RiskConfig.from_env()

    def check_action(
        self,
        *,
        task_id: str | None,
        action_type: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = payload or {}
        violations: list[str] = []
        rules: list[dict[str, Any]] = []

        def rule(rule_id: str, passed: bool, message: str) -> None:
            rules.append({"rule_id": rule_id, "passed": bool(passed), "message": message})
            if not passed:
                violations.append(f"{rule_id}: {message}")

        risk_level = "write_high_risk" if action_type in HIGH_RISK_ACTIONS else data.get("risk_level", "simulation")
        notional = _float(data.get("notional") or data.get("notional_usdt") or 0.0)
        asset_exposure = _float(data.get("asset_exposure") or data.get("asset_exposure_pct") or 0.0)
        daily_loss = _float(data.get("daily_loss") or data.get("daily_loss_usdt") or 0.0)
        strategy_id = data.get("strategy_id")

        if action_type in {"live_order", "paper_to_live_promotion"}:
            rule("RULE-001", False, "Live trading is disabled by default for the harness.")
            rule(
                "RULE-002",
                self.config.live_trading_enabled,
                "LIVE_TRADING_ENABLED=true is required for live trading actions.",
            )
            rule(
                "RULE-003",
                bool(data.get("approval_id")) or not self.config.require_approval_for_live,
                "Human approval is required for live trading actions.",
            )
        elif action_type in HIGH_RISK_ACTIONS:
            rule(
                "RULE-003",
                bool(data.get("approval_id")),
                "Human approval is required for high-risk actions.",
            )

        if notional:
            rule(
                "RULE-004",
                notional <= self.config.max_order_notional,
                f"Order notional {notional:.2f} must be <= {self.config.max_order_notional:.2f}.",
            )
        if asset_exposure:
            rule(
                "RULE-005",
                asset_exposure <= self.config.max_asset_exposure,
                f"Asset exposure {asset_exposure:.4f} must be <= {self.config.max_asset_exposure:.4f}.",
            )
        rule(
            "RULE-006",
            daily_loss < self.config.max_daily_loss,
            f"Daily loss {daily_loss:.2f} must be < {self.config.max_daily_loss:.2f}.",
        )
        if action_type in {"live_order", "paper_to_live_promotion"}:
            rule(
                "RULE-007",
                self.store.has_backtest_result(str(strategy_id)) if strategy_id else False,
                "Strategy must have a backtest record before live promotion.",
            )
            rule(
                "RULE-008",
                self.store.has_paper_order(str(strategy_id)) if strategy_id else False,
                "Strategy must have a paper trading record before live promotion.",
            )
        rule("RULE-009", True, "Risk check is persisted as part of this evaluation.")
        if action_type in HIGH_RISK_ACTIONS:
            rule(
                "RULE-010",
                self.store.has_audit_events(task_id),
                "High-risk actions require an existing task audit trail.",
            )

        passed = not violations
        recommendation = "allow" if passed else "block"
        risk_check = self.store.record_risk_check(
            task_id=task_id,
            action_type=action_type,
            risk_level=risk_level,
            passed=passed,
            rules_checked=rules,
            violations=violations,
            recommendation=recommendation,
        )
        self.audit.record(
            "risk.checked",
            task_id=task_id,
            actor="risk_manager",
            message=f"Risk check {'passed' if passed else 'failed'} for {action_type}.",
            action=action_type,
            risk_level=risk_level,
            status="passed" if passed else "failed",
            metadata={"risk_check_id": risk_check["id"], "violations": violations},
        )
        if not passed:
            self.audit.record(
                "risk.rejected",
                task_id=task_id,
                actor="risk_manager",
                message=f"Risk rejected action: {action_type}",
                action=action_type,
                risk_level=risk_level,
                status="rejected",
                metadata={"risk_check_id": risk_check["id"], "violations": violations},
            )
        return {
            "passed": passed,
            "risk_level": risk_level,
            "rules_checked": rules,
            "violations": violations,
            "recommendation": recommendation,
            "risk_check_id": risk_check["id"],
            "requires_approval": action_type in HIGH_RISK_ACTIONS,
        }


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
