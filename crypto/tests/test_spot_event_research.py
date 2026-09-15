from copy import deepcopy
from types import SimpleNamespace

import pytest

from kquant_crypto.math_action_contract import CORE_SYMBOLS
from kquant_crypto.spot_event_research import (
    EventDataset,
    classify_event,
    fixed_horizon_outcome,
    load_event_contract,
    reprice_fixed_sequence_double_cost,
    replay_event_candidate,
)
from kquant_crypto.strategy_dual_mode_v1 import Bar


def _window(**overrides):
    value = {
        "event_return_15m": -0.03,
        "event_imbalance": -0.8,
        "event_quote_volume": 2000.0,
        "trailing_return_24h": -0.01,
        "event_low": 95.0,
        "event_close": 98.0,
        "confirmation_first_low": 95.0,
        "confirmation_second_low": 96.0,
        "confirmation_first_close": 97.0,
        "confirmation_second_close": 99.0,
        "confirmation_first_imbalance": 0.2,
        "confirmation_second_imbalance": 0.3,
    }
    value.update(overrides)
    return value


def _threshold():
    return {
        "return_q10": -0.02,
        "imbalance_q10": -0.5,
        "imbalance_q90": 0.5,
        "quote_volume_q90": 1000.0,
        "positive_return_q75": 0.02,
        "trailing_return_24h_q75": 0.03,
    }


def test_contract_is_bounded_and_fail_closed():
    contract = load_event_contract()
    assert contract["execution_enabled"] is False
    assert contract["admission_enabled"] is False
    assert [item["id"] for item in contract["candidates"]] == [
        "SELL_PRESSURE_REPAIR_6H",
        "BUY_PRESSURE_START_6H",
    ]
    assert contract["event_policy"]["primary_horizon_hours"] == 6
    assert contract["final_targets"]["legacy_10r_contract_resolved"] is False


def test_sell_pressure_event_requires_flow_and_two_closed_confirmations():
    assert classify_event(_window(), _threshold(), "SELL_PRESSURE_REPAIR_6H") == "EVENT"
    price_only = _window(event_imbalance=-0.1)
    assert classify_event(price_only, _threshold(), "SELL_PRESSURE_REPAIR_6H") == "PRICE_ONLY_CONTROL"
    broken_low = _window(confirmation_second_low=94.0)
    assert classify_event(broken_low, _threshold(), "SELL_PRESSURE_REPAIR_6H") is None


def test_buy_pressure_event_rejects_overextension_and_requires_flow_confirmation():
    event = _window(
        event_return_15m=0.01,
        event_imbalance=0.7,
        event_quote_volume=2000.0,
        trailing_return_24h=0.01,
        event_close=98.0,
        confirmation_second_close=99.0,
    )
    assert classify_event(event, _threshold(), "BUY_PRESSURE_START_6H") == "EVENT"
    assert (
        classify_event(
            _window(**{**event, "event_return_15m": 0.03}),
            _threshold(),
            "BUY_PRESSURE_START_6H",
        )
        is None
    )
    no_flow_confirmation = _window(**{**event, "confirmation_second_imbalance": -0.1})
    assert classify_event(no_flow_confirmation, _threshold(), "BUY_PRESSURE_START_6H") == "PRICE_ONLY_CONTROL"


def test_fixed_horizon_fill_occurs_at_signal_bar_open_and_costs_are_not_double_counted():
    bars = {
        index * 300: Bar(
            start=index * 300,
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=1.0,
        )
        for index in range(12)
    }
    result = fixed_horizon_outcome(bars, 0, 1, fee=0.001, slippage=0.0005)
    assert result["label_status"] == "MATURE"
    assert result["entry_reference"] == 100.0
    assert result["exit_reference"] == 100.5
    expected_entry = 100.0 * 1.0005
    expected_exit = 100.5 * 0.9995
    expected_fees = 0.001 * (expected_entry + expected_exit)
    expected = (expected_exit - expected_entry - expected_fees) / (expected_entry * 1.001)
    assert result["net_return"] == pytest.approx(expected)


def test_fixed_horizon_gap_is_censored_not_fabricated_loss():
    bars = {
        0: Bar(start=0, open=100, high=101, low=99, close=100, volume=1),
        300: Bar(start=300, open=100, high=101, low=99, close=100, volume=1),
    }
    result = fixed_horizon_outcome(bars, 0, 1, fee=0.001, slippage=0.0005)
    assert result == {"label_status": "CENSORED", "reason": "future_path_gap"}


def test_portfolio_replay_does_not_read_future_label_and_uses_stop_first():
    contract = deepcopy(load_event_contract())
    bars = {}
    for symbol in CORE_SYMBOLS:
        series = []
        for index in range(24):
            start = index * 300
            low = 90.0 if symbol == "BTCUSDT" and start == 300 else 99.0
            high = 120.0 if symbol == "BTCUSDT" and start == 300 else 101.0
            series.append(Bar(start=start, open=100.0, high=high, low=low, close=100.0, volume=1.0))
        bars[symbol] = {"5m": series}
    dataset = EventDataset(SimpleNamespace(bars=bars), {}, "synthetic", {})
    row = {
        "sample_id": "sample",
        "candidate_id": "SELL_PRESSURE_REPAIR_6H",
        "sample_type": "EVENT",
        "fold": 1,
        "symbol": "BTCUSDT",
        "signal_time": 300,
        "stop": 95.0,
        "target": 110.0,
    }
    fold = {
        "fold": 1,
        "evaluation_start": 0,
        "evaluation_end_exclusive": 7200,
        "last_entry_time_exclusive": 3600,
    }
    result = replay_event_candidate([row], dataset, fold, contract, "SELL_PRESSURE_REPAIR_6H")
    assert len(result["trades"]) == 1
    assert result["trades"][0]["exit_reason"] == "stop"
    assert result["trades"][0]["label_status"] == "MATURE"


def test_double_cost_repricing_retains_base_r_denominator():
    contract = load_event_contract()
    trade = {
        "entry_reference": 100.0,
        "exit_reference": 103.0,
        "quantity": 2.0,
        "base_r_per_unit": 4.0,
        "net_pnl": 0.0,
        "net_r": 0.0,
    }
    result = reprice_fixed_sequence_double_cost([trade], contract)[0]
    expected_entry = 100.0 * 1.001
    expected_exit = 103.0 * 0.999
    expected_unit_pnl = expected_exit - expected_entry - 0.002 * (expected_entry + expected_exit)
    assert result["net_r"] == pytest.approx(expected_unit_pnl / 4.0)
    assert result["risk_denominator"] == "BASE_R_UNCHANGED"
