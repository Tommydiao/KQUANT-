from dataclasses import replace

from kquant_crypto.hybrid_dataset import Dataset
from kquant_crypto.math_action_contract import CORE_SYMBOLS, load_math_action_contract
from kquant_crypto.math_action_dataset import _net_r_long, build_spot_long_panel
from kquant_crypto.strategy_dual_mode_v1 import Bar


def _dataset(hours=240):
    bars = {}
    provenance = {}
    for symbol_index, symbol in enumerate(CORE_SYMBOLS):
        hourly = []
        fives = []
        price = 100.0 + symbol_index * 10
        for hour in range(hours):
            hour_start = hour * 3600
            hour_open = price
            children = []
            for minute in range(12):
                start = hour_start + minute * 300
                close = price * (1.0 + 0.0001 * (symbol_index + 1))
                child = Bar(start=start, open=price, high=max(price, close) * 1.0002,
                            low=min(price, close) * 0.9998, close=close, volume=1000.0 + hour)
                children.append(child)
                fives.append(child)
                price = close
            hourly.append(Bar(start=hour_start, open=hour_open,
                              high=max(bar.high for bar in children), low=min(bar.low for bar in children),
                              close=children[-1].close, volume=sum(bar.volume for bar in children)))
        bars[symbol] = {"1h": hourly, "5m": fives}
        provenance[symbol] = {"1h": {}, "5m": {}}
    manifest = {"source": "binance:spot:market_specific_compacted_closed_klines"}
    return Dataset(bars, provenance, manifest, [], hours * 3600, "synthetic-test-hash")


def test_panel_uses_closed_features_and_future_path():
    rows, audit = build_spot_long_panel(_dataset(), load_math_action_contract())
    assert rows
    assert audit["perpetual_short"]["status"] == "DATA_BLOCKED"
    assert all(row["feature_snapshot_frozen_at"] == row["signal_time"] for row in rows)
    assert all(max(row["feature_as_of"].values()) <= row["signal_time"] for row in rows)
    assert all(row["label_horizon_end"] > row["signal_time"] for row in rows)


def test_future_prices_do_not_change_historical_features():
    contract = load_math_action_contract()
    original = _dataset()
    rows_before, _ = build_spot_long_panel(original, contract)
    cutoff = rows_before[0]["signal_time"]
    last = original.bars["BTCUSDT"]["5m"][-1]
    original.bars["BTCUSDT"]["5m"][-1] = replace(
        last,
        high=last.high * 10,
        close=last.close * 10,
    )
    rows_after, _ = build_spot_long_panel(original, contract)
    before = next(row for row in rows_before if row["symbol"] == "BTCUSDT" and row["signal_time"] == cutoff)
    after = next(row for row in rows_after if row["symbol"] == "BTCUSDT" and row["signal_time"] == cutoff)
    assert before["features"] == after["features"]
    assert before["feature_snapshot_hash"] == after["feature_snapshot_hash"]


def test_same_bar_stop_and_target_uses_stop_first():
    bars = [Bar(start=0, open=100.0, high=103.0, low=98.0, close=101.0, volume=1.0)]
    outcome = _net_r_long(
        bars,
        stop=99.0,
        target=102.0,
        fee=0.001,
        slippage=0.0005,
        horizon_end=300,
    )
    assert outcome["exit_reason"] == "stop"
    assert outcome["net_r"] < 0


def test_entry_gap_outside_plan_is_not_backfilled():
    bars = [Bar(start=0, open=103.0, high=104.0, low=102.0, close=103.5, volume=1.0)]
    outcome = _net_r_long(
        bars,
        stop=99.0,
        target=102.0,
        fee=0.001,
        slippage=0.0005,
        horizon_end=300,
    )
    assert outcome["fill_status"] == "NOT_FILLED"
    assert outcome["label_status"] == "UNAVAILABLE"


def test_completed_stop_before_later_gap_remains_mature():
    bars = [Bar(start=0, open=100.0, high=100.5, low=98.0, close=99.0, volume=1.0)]
    outcome = _net_r_long(
        bars,
        stop=99.0,
        target=102.0,
        fee=0.001,
        slippage=0.0005,
        horizon_end=600,
        path_complete=False,
    )
    assert outcome["label_status"] == "MATURE"
    assert outcome["exit_reason"] == "stop"


def test_unresolved_position_before_gap_is_censored_not_unfilled():
    bars = [Bar(start=0, open=100.0, high=100.5, low=99.5, close=100.1, volume=1.0)]
    outcome = _net_r_long(
        bars,
        stop=99.0,
        target=102.0,
        fee=0.001,
        slippage=0.0005,
        horizon_end=600,
        path_complete=False,
    )
    assert outcome["fill_status"] == "FILLED"
    assert outcome["label_status"] == "CENSORED"
