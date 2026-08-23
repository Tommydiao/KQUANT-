from __future__ import annotations

from kquant_crypto.evaluation_agent import EvaluationAgent
from kquant_crypto.instruction_models import InstructionState
from kquant_crypto.instruction_store import list_current_instructions, list_instruction_events, list_instructions
from kquant_crypto.realtime_supervisor import RealtimeSupervisor
from kquant_crypto.notifications import NotificationHub


def draft(**overrides):
    value = {
        "plan_id": "plan_instruction_1",
        "asset_id": "cex:binance:spot:SOLUSDT",
        "symbol": "SOLUSDT",
        "asset_type": "cex_spot",
        "strategy_version": "crypto_early_v1.0.0",
        "identity_status": "known",
        "data_quality_status": "live",
        "security_status": "pass",
        "liquidity_status": "pass",
        "market_regime": "RISK_ON",
        "model_status": "passed",
        "factor_snapshot_hash": "factor-1",
        "snapshot_bindings": {
            "market": "market-1", "regime": "regime-1", "factor": "factor-1",
            "security": "security-1", "liquidity": "liquidity-1", "derivative": "derivative-1",
            "signal": "signal-1", "plan": "plan_instruction_1", "model": "model-1",
            "universe": "universe-1", "eval_policy": "crypto_eval_v1.0.2",
        },
        "entry_zone": [100, 101],
        "stop_zone": [96, 97],
        "target_zone": [110, 112],
        "risk_reward": 2.5,
        "valid_until": "2099-01-01T00:00:00+00:00",
        "invalid_conditions": ["close_below_stop"],
        "requested_execution_class": "paper_only",
    }
    value.update(overrides)
    return value


def test_eval_result_creates_monitoring_instruction_and_deduplicates(settings):
    supervisor = RealtimeSupervisor(settings.db_path, NotificationHub())
    evaluation = EvaluationAgent(settings.db_path).evaluate(draft()).to_mapping()
    first = supervisor.accept_evaluation(evaluation)
    second = supervisor.accept_evaluation(evaluation)

    assert first["created"] is True
    assert first["instruction"]["state"] == InstructionState.MONITORING.value
    assert first["instruction"]["allowed_alert"] is False
    assert second["created"] is False
    assert supervisor.status()["duplicates_suppressed"] == 1
    assert len(list_instructions(settings.db_path)) == 1
    assert len(list_instruction_events(settings.db_path, first["instruction"]["instruction_id"])) == 1


def test_rejected_eval_cannot_become_actionable_instruction(settings):
    supervisor = RealtimeSupervisor(settings.db_path, NotificationHub())
    evaluation = EvaluationAgent(settings.db_path).evaluate(draft(security_status="unknown")).to_mapping()
    result = supervisor.accept_evaluation(evaluation)

    assert result["instruction"]["state"] == InstructionState.INVALIDATED.value
    assert result["alert"] is None
    assert list_current_instructions(settings.db_path) == []


def test_newer_terminal_state_hides_older_monitoring_projection(settings):
    supervisor = RealtimeSupervisor(settings.db_path, NotificationHub())
    first = EvaluationAgent(settings.db_path).evaluate(draft()).to_mapping()
    supervisor.accept_evaluation(first)
    second = EvaluationAgent(settings.db_path).evaluate(draft(
        plan_id="plan_instruction_2",
        security_status="unknown",
        snapshot_bindings={
            "market": "market-2", "regime": "regime-2", "factor": "factor-2",
            "security": "security-2", "liquidity": "liquidity-2", "derivative": "derivative-2",
            "signal": "signal-2", "plan": "plan_instruction_2", "model": "model-2",
            "universe": "universe-2", "eval_policy": "crypto_eval_v1.0.2",
        },
        factor_snapshot_hash="factor-2",
    )).to_mapping()
    supervisor.accept_evaluation(second)

    assert list_current_instructions(settings.db_path) == []


def test_alert_agent_is_downstream_of_eval_decision(settings):
    from kquant_crypto.alert_agent import emit_evaluated_alert

    hub = NotificationHub()
    assert emit_evaluated_alert(
        settings.db_path,
        hub,
        {"evaluation_status": "passed", "decision": "WATCH_ONLY", "allowed_alert": True},
        title="should not send",
        body="should not send",
    ) is None
