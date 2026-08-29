from __future__ import annotations

from datetime import UTC, datetime

from kquant_crypto.roll_engine import RollAction, RollInput, evaluate_roll
from kquant_crypto.roll_store import (
    list_current_roll_decisions,
    record_roll_ledger_event,
    save_roll_decision,
)


def _valid(**overrides):
    value = {
        "asset_id": "asset:ETH",
        "symbol": "ETH",
        "asset_type": "crypto_spot",
        "as_of_time": "2026-08-23T12:00:00+00:00",
        "data_cutoff_time": "2026-08-23T11:59:00+00:00",
        "source_status": "live",
        "coverage": 1.0,
        "hard_veto": False,
        "market_state": "BULL",
        "state_probability": 0.82,
        "target_before_stop_probability": 0.72,
        "positive_return_probability": 0.70,
        "drawdown_probability": 0.18,
        "realized_profit": 0.0,
        "floating_pnl": 0.0,
        "current_exposure": 0.0,
        "proposed_capital": 0.0,
        "probability_improvement": 0.0,
        "feature_snapshot_id": "bayes_features_1",
        "model_version": "crypto_bayesian_v1.0.0",
        "source_snapshot_ids": ["market_1", "regime_1"],
    }
    value.update(overrides)
    return RollInput.from_mapping(value)


def test_roll_buy_is_deterministic_and_research_only():
    first = evaluate_roll(_valid())
    second = evaluate_roll(_valid())
    assert first.action == RollAction.ROLL_BUY
    assert first.roll_id == second.roll_id
    assert first.research_only is True
    assert first.roll_capital == 0


def test_floating_loss_cannot_become_roll_add():
    decision = evaluate_roll(_valid(
        current_exposure=1000,
        realized_profit=250,
        proposed_capital=250,
        floating_pnl=-40,
        probability_improvement=0.20,
    ))
    assert decision.action in {RollAction.HOLD_CORE, RollAction.REDUCE}
    assert "floating_loss_no_add" in decision.warnings
    assert decision.roll_capital == 0


def test_future_cutoff_and_unknown_source_block_roll():
    decision = evaluate_roll(_valid(
        data_cutoff_time="2026-08-23T12:01:00+00:00",
        source_status="partial",
    ))
    assert decision.action == RollAction.DATA_BLOCKED
    assert "future_data_cutoff" in decision.blockers
    assert "source_status_not_verified" in decision.blockers


def test_zero_drawdown_probability_is_not_replaced_by_default():
    item = _valid(drawdown_probability=0.0)
    assert item.drawdown_probability == 0.0
    assert evaluate_roll(item).action == RollAction.ROLL_BUY


def test_unknown_asset_and_stress_state_cannot_show_roll_capital():
    unknown = evaluate_roll(_valid(symbol="UNKNOWN", realized_profit=100, proposed_capital=100))
    assert unknown.action == RollAction.DATA_BLOCKED
    assert "asset_mapping_missing" in unknown.blockers
    stress = evaluate_roll(_valid(
        current_exposure=500,
        realized_profit=100,
        proposed_capital=100,
        market_state="BEAR_STRESS",
    ))
    assert stress.action == RollAction.EXIT_REVIEW
    assert stress.roll_capital == 0


def test_asset_identity_must_match_symbol_and_instrument():
    decision = evaluate_roll(_valid(asset_id="asset:ETH:wrong-record"))
    assert decision.action == RollAction.DATA_BLOCKED
    assert "asset_identity_mismatch" in decision.blockers


def test_roll_strategy_version_is_frozen_and_mismatches_are_blocked():
    decision = evaluate_roll(_valid(strategy_version="crypto_roll_v0.9.0"))
    assert decision.action == RollAction.DATA_BLOCKED
    assert "strategy_version_mismatch" in decision.blockers


def test_listed_roll_requires_actual_instrument_series_and_rejects_underlying_proxy():
    missing_series = evaluate_roll(_valid(
        asset_id="asset:ETHU",
        symbol="ETHU",
        asset_type="crypto_leveraged_etf",
        instrument_id="listed:US:ETHU",
    ))
    assert missing_series.action == RollAction.DATA_BLOCKED
    assert "listed_instrument_data_unavailable" in missing_series.blockers

    proxy_series = evaluate_roll(_valid(
        asset_id="asset:ETHU",
        symbol="ETHU",
        asset_type="crypto_leveraged_etf",
        instrument_id="listed:US:ETHU",
        instrument_data_status="actual",
        underlying_proxy_used=True,
    ))
    assert proxy_series.action == RollAction.DATA_BLOCKED
    assert "underlying_proxy_substitution_forbidden" in proxy_series.blockers


def test_realized_profit_only_add_and_rotation():
    decision = evaluate_roll(_valid(
        current_exposure=1000,
        realized_profit=250,
        proposed_capital=300,
        probability_improvement=0.10,
    ))
    assert decision.action == RollAction.ROLL_ADD
    assert decision.roll_capital == 250
    rotated = evaluate_roll(_valid(
        current_exposure=1000,
        realized_profit=250,
        proposed_capital=250,
        probability_improvement=0.10,
        current_score=0.50,
        rotation_score=0.80,
        rotation_target="asset:SOL",
    ))
    assert rotated.action == RollAction.ROTATE_TO


def test_roll_store_and_ledger_are_auditable(settings):
    decision = evaluate_roll(_valid())
    saved, created = save_roll_decision(settings.db_path, decision)
    assert created is True
    assert saved["strategy_version"] == "crypto_roll_v1.0.0"
    duplicate, created_again = save_roll_decision(settings.db_path, decision)
    assert created_again is False
    assert duplicate["roll_id"] == decision.roll_id
    assert list_current_roll_decisions(settings.db_path)[0]["roll_id"] == decision.roll_id
    entry = record_roll_ledger_event(
        settings.db_path,
        asset_id="asset:ETH",
        symbol="ETH",
        event_type="realized_profit",
        realized_profit=100,
        rolled_capital=60,
        remaining_risk=40,
        occurred_at=datetime.now(UTC).isoformat(),
        roll_id=decision.roll_id,
    )
    assert entry["rolled_capital"] == 60
