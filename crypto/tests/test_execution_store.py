from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kquant_crypto.execution_models import ExecutionIntent
from kquant_crypto.execution_store import save_execution_intent, testnet_release_gate as release_gate


def test_execution_intent_is_idempotent_by_eval_and_material_state(settings):
    now = datetime.now(UTC)
    first = ExecutionIntent.create(
        intent_id="intent_first",
        evaluation_id="eval_one",
        strategy_version="crypto_early_v1.0.0",
        symbol="BTCUSDT",
        market_type="spot",
        direction="long",
        entry_limit=100,
        stop_price=95,
        target_price=110,
        validation_gate_status="PASS",
        material_state_hash="same_state",
        expires_at=(now + timedelta(hours=1)).isoformat(),
    )
    second = ExecutionIntent.create(**{**first.as_dict(), "intent_id": "intent_second"})
    assert save_execution_intent(settings.db_path, first)["intent_id"] == "intent_first"
    assert save_execution_intent(settings.db_path, second)["intent_id"] == "intent_first"


def test_testnet_release_gate_starts_no_go(settings):
    result = release_gate(settings.db_path)
    assert result["status"] == "NO_GO"
    assert result["observed"]["closed_trades"] == 0
    assert result["checks"]["calendar_days"] is False
