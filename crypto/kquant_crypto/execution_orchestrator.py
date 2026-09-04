from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .evaluation_store import get_trade_plan
from .execution_models import ExecutionIntent
from .execution_store import save_execution_intent
from .strategy_manifest import strategy_manifest
from .universe_catalog import candidate_instrument
from .validation_store import latest_validation_gate_for_unit


class ExecutionAdmissionError(ValueError):
    pass


def _price(values: Any, *, mode: str) -> float:
    items = [float(value) for value in (values or ()) if float(value) > 0]
    if not items:
        raise ExecutionAdmissionError(f"{mode}_price_missing")
    return max(items) if mode in {"entry", "stop"} else min(items)


def _expired(value: str | None, now: datetime) -> bool:
    if not value:
        return True
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed <= now.astimezone(UTC)


class ExecutionOrchestrator:
    """The only bridge from a persisted EVAL decision to account-aware execution."""

    def __init__(self, db_path: Path, controller: Any):
        self.db_path = db_path
        self.controller = controller
        self.admissions_seen = 0
        self.intents_created = 0
        self.blocked = 0
        self.last_result: dict[str, Any] | None = None

    def admit(self, evaluation: dict[str, Any], *, execute: bool = True) -> dict[str, Any]:
        self.admissions_seen += 1
        blockers: list[str] = []
        now = datetime.now(UTC)
        plan = get_trade_plan(self.db_path, str(evaluation.get("plan_id") or ""))
        strategy_version = str(evaluation.get("strategy_version") or "")
        symbol = str(evaluation.get("symbol") or "").upper()
        decision = str(evaluation.get("decision") or "")
        if decision != "SHADOW_ELIGIBLE" or not bool(evaluation.get("allowed_shadow")):
            blockers.append("eval_not_shadow_eligible")
        manifest = strategy_manifest(strategy_version)
        if manifest is None or not manifest.executable:
            blockers.append("strategy_execution_not_supported")
        market_type = manifest.market_type if manifest else str(evaluation.get("market_type") or "spot").lower()
        direction = manifest.direction if manifest else str(evaluation.get("direction") or "long").lower()
        gate = latest_validation_gate_for_unit(
            self.db_path,
            strategy_version=strategy_version,
            symbol=symbol,
            market_type=market_type,
            direction=direction,
        )
        if not gate or str(gate.get("status") or "").upper() != "PASS":
            blockers.append("validation_gate_not_passed")
        candidate = candidate_instrument(symbol)
        if candidate and candidate.market_type != market_type:
            blockers.append("candidate_market_type_mismatch")
        if candidate and symbol == "HYPEUSDT" and market_type != "perpetual":
            blockers.append("hype_spot_strategy_forbidden")
        if symbol not in self.controller.settings.symbols:
            blockers.append("symbol_not_allowlisted")
        if plan is None:
            blockers.append("trade_plan_missing")
        elif _expired(plan.get("valid_until"), now):
            blockers.append("trade_plan_expired")
        if blockers:
            self.blocked += 1
            self.last_result = {"status": "blocked", "blockers": list(dict.fromkeys(blockers)), "intent": None}
            return self.last_result

        assert plan is not None
        try:
            entry = _price(plan.get("entry_zone"), mode="entry")
            stop = _price(plan.get("stop_zone"), mode="stop")
            target = _price(plan.get("target_zone"), mode="target")
        except ExecutionAdmissionError as exc:
            self.blocked += 1
            self.last_result = {"status": "blocked", "blockers": [str(exc)], "intent": None}
            return self.last_result
        if not (stop < entry < target):
            self.blocked += 1
            self.last_result = {"status": "blocked", "blockers": ["invalid_long_plan_geometry"], "intent": None}
            return self.last_result

        intent = ExecutionIntent.create(
            evaluation_id=evaluation["evaluation_id"],
            strategy_version=strategy_version,
            symbol=symbol,
            market_type=market_type,
            direction=direction,
            entry_limit=entry,
            stop_price=stop,
            target_price=target,
            validation_gate_status="PASS",
            material_state_hash=str(evaluation.get("material_state_hash") or plan.get("material_state_hash") or ""),
            created_at=now.isoformat(),
            expires_at=str(plan["valid_until"]),
            requested_risk_fraction=min(
                float(getattr(self.controller.settings, "risk_per_trade_fraction", 0.01)),
                float(candidate.risk_fraction_cap if candidate else 0.01),
            ),
        )
        saved = save_execution_intent(self.db_path, intent)
        self.intents_created += 1
        execution = self.controller.execute_intent(intent, evaluation_decision=decision) if execute else None
        self.last_result = {"status": "submitted" if execution else "intent_created", "blockers": [], "intent": saved, "execution": execution}
        return self.last_result

    def status(self) -> dict[str, Any]:
        return {
            "admissions_seen": self.admissions_seen,
            "intents_created": self.intents_created,
            "blocked": self.blocked,
            "last_result": self.last_result,
        }
