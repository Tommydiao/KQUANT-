from kquant_crypto.math_action_baseline import (
    action_diagnostics,
    fit_ridge_baseline,
    predict_ridge,
    replay_action_policy,
)
from kquant_crypto.math_action_contract import CORE_SYMBOLS, load_math_action_contract


def _rows():
    contract = load_math_action_contract()
    features = contract["features"]["spot_long"]
    rows = []
    for hour in range(1200):
        partition = "DEVELOPMENT_TRAIN" if hour < 800 else "DEVELOPMENT_VALIDATION" if hour < 1000 else "DEVELOPMENT_DIAGNOSTIC"
        for index, symbol in enumerate(CORE_SYMBOLS):
            values = {name: (hour % 31) / 31 + index * 0.1 + feature_index * 0.01 for feature_index, name in enumerate(features)}
            rows.append({
                "sample_id": f"{hour}:{symbol}", "signal_time": hour * 3600,
                "symbol": symbol, "action": f"SPOT_LONG_{symbol}", "partition": partition,
                "fill_status": "FILLED", "label_status": "MATURE",
                "features": values, "net_r": values[features[0]] - 0.3,
                "signal_reference": 100.0 + index,
                "entry_price": 100.0 + index,
                "exit_price": 100.5 + index,
                "base_r_per_unit": 1.0,
                "net_pnl_per_unit": values[features[0]] - 0.3,
                "exit_time": hour * 3600 + 86400, "exit_reason": "time_exit",
            })
    return rows, contract


def test_ridge_is_reproducible_and_fail_closed():
    rows, contract = _rows()
    first = fit_ridge_baseline(rows, contract)
    second = fit_ridge_baseline(rows, contract)
    assert first == second
    predictions = predict_ridge(rows, first)
    report = action_diagnostics(rows, predictions)
    assert report["status"] == "DESCRIPTIVE_DEV_ONLY"
    assert report["independent_oos"] is False
    assert report["metrics"]["DEVELOPMENT_VALIDATION"]["selected_actions"] > 0


def test_selection_does_not_use_future_label_availability():
    rows, contract = _rows()
    artifact = fit_ridge_baseline(rows, contract)
    predictions = predict_ridge(rows, artifact)
    first_time = min(row["signal_time"] for row in rows if row["partition"] == "DEVELOPMENT_TRAIN")
    candidates = [row for row in rows if row["signal_time"] == first_time]
    predicted = {item["sample_id"]: item for item in predictions}
    selected = max(candidates, key=lambda row: predicted[row["sample_id"]]["predicted_net_r"])
    predicted[selected["sample_id"]]["predicted_net_r"] = 10.0
    selected["fill_status"] = "NOT_FILLED"
    selected["label_status"] = "UNAVAILABLE"
    selected["unavailable_reason"] = "test_missing_future_path"

    diagnostics = action_diagnostics(rows, predictions, minimum_predicted_net_r=-100.0)
    first = next(item for item in diagnostics["selected"] if item["signal_time"] == first_time)
    assert first["sample_id"] == selected["sample_id"]
    assert first["label_status"] == "UNAVAILABLE"

    replay = replay_action_policy(rows, predictions, contract, score_field="predicted_net_r")
    event = next(item for item in replay["events"] if item["signal_time"] == first_time)
    assert event["action"] == "WAIT"
    assert event["reason"] == "test_missing_future_path"
