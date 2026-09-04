from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from kquant_crypto.evaluation_models import TradePlanDraft
from kquant_crypto.evaluation_store import save_trade_plan
from kquant_crypto.execution_orchestrator import ExecutionOrchestrator


class _Controller:
    def __init__(self):
        self.settings = SimpleNamespace(symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"))
        self.executed = []

    def execute_intent(self, intent, *, evaluation_decision):
        self.executed.append(intent)
        return {"status": "risk_blocked", "decision": evaluation_decision}


def _evaluation(plan_id: str, **updates):
    value = {
        "evaluation_id": "eval_1", "plan_id": plan_id, "symbol": "BTCUSDT",
        "strategy_version": "crypto_spot_momentum_v2.0.0",
        "decision": "SHADOW_ELIGIBLE", "allowed_shadow": True,
        "material_state_hash": "material_1",
    }
    value.update(updates)
    return value


def _plan() -> TradePlanDraft:
    now = datetime.now(UTC)
    return TradePlanDraft.from_mapping({
        "plan_id": "plan_1", "asset_id": "asset:BTC", "symbol": "BTCUSDT",
        "asset_type": "cex_spot", "strategy_version": "crypto_spot_momentum_v2.0.0",
        "entry_zone": [99.5, 100.0], "stop_zone": [95.0, 96.0],
        "target_zone": [108.0, 110.0], "factor_snapshot_hash": "factor_1",
        "source_snapshot_ids": ["snapshot_1"], "snapshot_bindings": {"market": "snapshot_1"},
        "valid_from": now.isoformat(), "valid_until": (now + timedelta(minutes=30)).isoformat(),
        "material_state_hash": "material_1",
    })


def test_orchestrator_blocks_no_go_validation(settings):
    plan = _plan()
    save_trade_plan(settings.db_path, plan)
    controller = _Controller()
    result = ExecutionOrchestrator(settings.db_path, controller).admit(_evaluation(plan.plan_id))
    assert result["status"] == "blocked"
    assert "validation_gate_not_passed" in result["blockers"]
    assert controller.executed == []


def test_orchestrator_creates_intent_only_after_eval_and_gate(settings, monkeypatch):
    plan = _plan()
    save_trade_plan(settings.db_path, plan)
    monkeypatch.setattr(
        "kquant_crypto.execution_orchestrator.latest_validation_gate_for_unit",
        lambda *_, **__: {"status": "PASS"},
    )
    controller = _Controller()
    result = ExecutionOrchestrator(settings.db_path, controller).admit(_evaluation(plan.plan_id), execute=False)
    assert result["status"] == "intent_created"
    assert result["intent"]["symbol"] == "BTCUSDT"
    assert result["intent"]["validation_gate_status"] == "PASS"
    assert controller.executed == []


def test_orchestrator_rejects_non_allowlisted_symbol_before_intent(settings, monkeypatch):
    plan = TradePlanDraft.from_mapping({**_plan().to_mapping(), "plan_id": "plan_alt", "symbol": "DOGEUSDT"})
    save_trade_plan(settings.db_path, plan)
    monkeypatch.setattr(
        "kquant_crypto.execution_orchestrator.latest_validation_gate_for_unit",
        lambda *_, **__: {"status": "PASS"},
    )
    result = ExecutionOrchestrator(settings.db_path, _Controller()).admit(_evaluation(plan.plan_id, symbol="DOGEUSDT"))
    assert result["status"] == "blocked"
    assert "symbol_not_allowlisted" in result["blockers"]
