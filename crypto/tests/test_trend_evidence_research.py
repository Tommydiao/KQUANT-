from dataclasses import replace

from kquant_crypto.hybrid_dataset import Dataset
from kquant_crypto.math_action_contract import CORE_SYMBOLS, canonical_hash
from kquant_crypto.strategy_dual_mode_v1 import Bar
from kquant_crypto.trend_evidence_research import (
    EnrichedDataset,
    MicrostructureBar,
    build_candidate_panel,
    load_trend_contract,
    run_ridge_walk_forward,
    walk_forward_folds,
)


def _dataset(hours: int = 1200) -> EnrichedDataset:
    bars = {}
    provenance = {}
    micro = {}
    for symbol_index, symbol in enumerate(CORE_SYMBOLS):
        hourly = []
        fives = []
        micro[symbol] = {}
        price = 100.0 + symbol_index * 10.0
        for hour in range(hours):
            hour_start = hour * 3600
            hour_open = price
            children = []
            for minute in range(12):
                start = hour_start + minute * 300
                drift = 0.00005 * (symbol_index + 1) + (0.00002 if hour % 48 < 24 else -0.00001)
                close = price * (1.0 + drift)
                bar = Bar(
                    start=start,
                    open=price,
                    high=max(price, close) * 1.0005,
                    low=min(price, close) * 0.9995,
                    close=close,
                    volume=1000.0 + hour + minute,
                )
                children.append(bar)
                fives.append(bar)
                price = close
            hourly.append(
                Bar(
                    start=hour_start,
                    open=hour_open,
                    high=max(item.high for item in children),
                    low=min(item.low for item in children),
                    close=children[-1].close,
                    volume=sum(item.volume for item in children),
                )
            )
            quote = (1_000_000.0 + hour * 1000.0) * (symbol_index + 1)
            buy_share = 0.48 + 0.04 * ((hour + symbol_index) % 12) / 11.0
            micro[symbol][hour_start] = MicrostructureBar(
                quote_volume=quote,
                trade_count=1000 + hour + symbol_index,
                taker_buy_quote_volume=quote * buy_share,
                source_hash=f"{symbol}:{hour}",
            )
        bars[symbol] = {"1h": hourly, "5m": fives}
        provenance[symbol] = {"1h": {}, "5m": {}}
    manifest = {"window": {"start": 174 * 3600, "warmup_start": 0}}
    base = Dataset(bars, provenance, manifest, [], hours * 3600, "synthetic-base")
    content_hash = canonical_hash(
        {symbol: {str(stamp): vars(value) for stamp, value in values.items()} for symbol, values in micro.items()}
    )
    return EnrichedDataset(base=base, microstructure=micro, content_hash=content_hash, audit={})


def test_contract_is_fail_closed_and_candidate_set_is_bounded():
    contract = load_trend_contract()
    assert contract["execution_enabled"] is False
    assert contract["admission_enabled"] is False
    assert [item["id"] for item in contract["candidates"]] == [
        "H1_FLOW_24H",
        "H1_FLOW_72H",
        "H2_RESIDUAL_24H",
        "H2_RESIDUAL_72H",
    ]


def test_panel_uses_native_flow_and_respects_research_start():
    contract = load_trend_contract()
    rows, audit = build_candidate_panel(_dataset(), contract)
    assert rows
    assert audit["first_signal_time"] >= 174 * 3600
    flow = next(row for row in rows if row["candidate_id"] == "H1_FLOW_24H")
    assert "aggressor_imbalance_6h" in flow["features"]
    assert "trade_count_log_acceleration_6h" in flow["features"]
    assert flow["feature_snapshot_frozen_at"] == flow["signal_time"]
    assert flow["independent_oos"] is False


def test_future_bar_change_does_not_change_past_feature_snapshot():
    contract = load_trend_contract()
    dataset = _dataset()
    before, _ = build_candidate_panel(dataset, contract)
    sample = before[0]
    last = dataset.base.bars[sample["symbol"]]["5m"][-1]
    dataset.base.bars[sample["symbol"]]["5m"][-1] = replace(last, close=last.close * 2.0, high=last.high * 2.0)
    after, _ = build_candidate_panel(dataset, contract)
    matching = next(row for row in after if row["sample_id"] == sample["sample_id"])
    assert matching["features"] == sample["features"]
    assert matching["feature_snapshot_hash"] == sample["feature_snapshot_hash"]


def test_walk_forward_uses_three_purged_windows_and_train_only_transforms():
    contract = load_trend_contract()
    rows, _ = build_candidate_panel(_dataset(1800), contract)
    folds = walk_forward_folds(rows, contract)
    assert len(folds) == 3
    assert all(fold["evaluation_start"] - fold["training_end_exclusive"] >= 144 * 3600 for fold in folds)
    result = run_ridge_walk_forward(rows, contract)
    assert len(result["artifacts"]) == 12
    assert len(result["ablation_artifacts"]) == 12
    assert result["claims"]["independent_oos"] is False
