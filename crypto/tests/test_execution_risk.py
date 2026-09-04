from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kquant_crypto.config import ExecutionMode, ExecutionSettings
from kquant_crypto.execution_models import (
    AccountRiskSnapshot,
    ExchangePosition,
    ExecutionIntent,
    SymbolTradingRules,
)
from kquant_crypto.execution_risk import evaluate_execution_risk


def execution_settings(**changes) -> ExecutionSettings:
    values = {
        "mode": ExecutionMode.TESTNET,
        "autotrade_enabled": True,
        "testnet_api_key": "test-key",
        "testnet_api_secret": "test-secret",
    }
    values.update(changes)
    return ExecutionSettings(**values)


def intent(**changes) -> ExecutionIntent:
    now = datetime.now(UTC)
    values = {
        "evaluation_id": "eval_1",
        "strategy_version": "crypto_early_v1.0.0",
        "symbol": "BTCUSDT",
        "market_type": "spot",
        "direction": "long",
        "entry_limit": 100.0,
        "stop_price": 95.0,
        "target_price": 110.0,
        "validation_gate_status": "PASS",
        "material_state_hash": "state_1",
        "expires_at": (now + timedelta(hours=1)).isoformat(),
    }
    values.update(changes)
    return ExecutionIntent.create(**values)


def account(**changes) -> AccountRiskSnapshot:
    values = {
        "snapshot_id": "account_1",
        "mode": "testnet",
        "equity_usdt": 50.0,
        "available_usdt": 50.0,
        "daily_realized_pnl_usdt": 0.0,
    }
    values.update(changes)
    return AccountRiskSnapshot(**values)


def rules(**changes) -> SymbolTradingRules:
    values = {
        "symbol": "BTCUSDT",
        "market_type": "spot",
        "min_qty": 0.001,
        "step_size": 0.001,
        "min_notional": 5.0,
        "tick_size": 0.01,
    }
    values.update(changes)
    return SymbolTradingRules(**values)


def test_approved_quantity_respects_one_percent_risk_and_capital_limit():
    decision = evaluate_execution_risk(
        intent(), account(), rules(), execution_settings(), armed=True,
        evaluation_decision="SHADOW_ELIGIBLE",
    )
    assert decision.allowed is True
    assert decision.quantity == 0.1
    assert decision.estimated_risk_usdt == 0.5
    assert decision.estimated_notional == 10.0


def test_minimum_notional_is_skipped_instead_of_breaking_risk_cap():
    decision = evaluate_execution_risk(
        intent(), account(), rules(min_notional=20.0), execution_settings(), armed=True,
        evaluation_decision="SHADOW_ELIGIBLE",
    )
    assert decision.allowed is False
    assert "minimum_notional_not_met" in decision.blockers
    assert decision.estimated_risk_usdt <= 0.5


def test_daily_loss_and_existing_position_block_new_entry():
    position = ExchangePosition("ETHUSDT", "spot", "long", 0.2, 100.0, 101.0, 95.0)
    decision = evaluate_execution_risk(
        intent(),
        account(daily_realized_pnl_usdt=-0.5, positions=(position,)),
        rules(),
        execution_settings(),
        armed=True,
        evaluation_decision="SHADOW_ELIGIBLE",
    )
    assert decision.allowed is False
    assert "daily_loss_limit_reached" in decision.blockers
    assert "existing_position_blocks_new_entry" in decision.blockers


def test_spot_short_and_nonfinal_eval_are_rejected():
    decision = evaluate_execution_risk(
        intent(direction="short", stop_price=105.0, target_price=90.0),
        account(), rules(), execution_settings(), armed=True,
        evaluation_decision="PAPER_REVIEW",
    )
    assert decision.allowed is False
    assert "spot_short_forbidden" in decision.blockers
    assert "eval_not_shadow_eligible" in decision.blockers


def test_disabled_mode_is_fail_closed():
    decision = evaluate_execution_risk(
        intent(), account(), rules(), ExecutionSettings(), armed=False,
        evaluation_decision="SHADOW_ELIGIBLE",
    )
    assert decision.allowed is False
    assert {"execution_disabled", "autotrade_disabled", "credentials_missing", "runtime_not_armed"} <= set(decision.blockers)


def test_available_balance_must_cover_spot_notional():
    decision = evaluate_execution_risk(
        intent(), account(available_usdt=5.0), rules(), execution_settings(), armed=True,
        evaluation_decision="SHADOW_ELIGIBLE",
    )
    assert decision.allowed is False
    assert "insufficient_available_balance" in decision.blockers
