from copy import deepcopy

from kquant_crypto.trend_evidence_controls import (
    block_bootstrap_trade_uncertainty,
    load_controls_contract,
    matched_random_predictions,
    price_momentum_predictions,
)
from kquant_crypto.trend_evidence_research import build_candidate_panel, load_trend_contract
from kquant_crypto.trend_evidence_research import replay_candidate_fold

from test_trend_evidence_research import _dataset


def test_controls_contract_is_fail_closed_and_registered():
    contract = load_controls_contract()
    assert contract["random_control"]["repetitions"] == 200
    assert contract["uncertainty"]["paths"] == 2000
    assert contract["claims"]["runtime_admission"] is False


def test_price_momentum_control_does_not_read_future_labels():
    dataset = _dataset()
    contract = load_trend_contract()
    rows, _ = build_candidate_panel(dataset, contract)
    folds = [
        {
            "fold": 1,
            "evaluation_start": rows[0]["signal_time"],
            "evaluation_end_exclusive": rows[0]["signal_time"] + 12 * 3600,
            "last_entry_time_exclusive": rows[0]["signal_time"] + 12 * 3600,
        }
    ]
    original = price_momentum_predictions(rows, folds, dataset, contract["candidates"])
    changed = deepcopy(rows)
    for row in changed:
        row["net_r"] = -999.0
        row["label_status"] = "CENSORED"
    repeated = price_momentum_predictions(changed, folds, dataset, contract["candidates"])
    assert original == repeated


def test_matched_random_control_is_reproducible_and_matches_opportunity_count():
    dataset = _dataset()
    contract = load_trend_contract()
    rows, _ = build_candidate_panel(dataset, contract)
    start = rows[0]["signal_time"]
    fold = {
        "fold": 1,
        "evaluation_start": start,
        "evaluation_end_exclusive": start + 24 * 3600,
        "last_entry_time_exclusive": start + 24 * 3600,
    }
    counts = {(candidate["id"], 1): 4 for candidate in contract["candidates"]}
    first = matched_random_predictions(rows, [fold], contract["candidates"], counts, seed=7)
    second = matched_random_predictions(rows, [fold], contract["candidates"], counts, seed=7)
    assert first == second
    for candidate in contract["candidates"]:
        assert sum(row["candidate_id"] == candidate["id"] for row in first) == 4


def test_utc_block_bootstrap_is_deterministic_and_reports_stability_limit():
    controls = load_controls_contract()
    folds = [{"fold": 1, "evaluation_start": 0, "evaluation_end_exclusive": 14 * 86400}]
    trades = [
        {"fold": 1, "signal_time": day * 86400, "net_r": 0.2 if day % 2 else -0.1}
        for day in range(14)
    ]
    first = block_bootstrap_trade_uncertainty(trades, folds, controls)
    second = block_bootstrap_trade_uncertainty(trades, folds, controls)
    assert first == second
    assert first["completed_paths"] == 2000
    assert first["stability"] == "UNSTABLE_LESS_THAN_12_UTC_WEEKS"
    assert first["claims"]["runtime_admission"] is False


def test_sparse_control_timeline_preserves_entries_and_exits():
    dataset = _dataset()
    contract = load_trend_contract()
    rows, _ = build_candidate_panel(dataset, contract)
    start = rows[0]["signal_time"]
    fold = {
        "fold": 1,
        "evaluation_start": start,
        "evaluation_end_exclusive": start + 48 * 3600,
        "last_entry_time_exclusive": start + 24 * 3600,
    }
    predictions = price_momentum_predictions(rows, [fold], dataset, contract["candidates"])
    predictions = [row for row in predictions if row["candidate_id"] == "H1_FLOW_24H"]
    full = replay_candidate_fold(rows, predictions, dataset, fold, contract)
    sparse = replay_candidate_fold(
        rows,
        predictions,
        dataset,
        fold,
        contract,
        timeline_mode="decision_events",
    )
    assert [row["sample_id"] for row in full["trades"]] == [row["sample_id"] for row in sparse["trades"]]
    assert [row["net_r"] for row in full["trades"]] == [row["net_r"] for row in sparse["trades"]]
