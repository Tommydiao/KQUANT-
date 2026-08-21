from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from kquant.market_store import persist_canonical_candles
from kquant.stock_quant import build_stock_quant_dataset
from kquant.stock_quant_validation import (
    build_stock_quant_cache_dataset,
    run_stock_quant_validation,
)
from kquant.stock_store import connect
from kquant.quant_dataset import DatasetIntegrityError


def _items(count: int = 210) -> list[dict]:
    start = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    rows: list[dict] = []
    for index in range(count):
        for symbol_index, symbol in enumerate(("AAA", "BBB", "CCC")):
            positive = (index + symbol_index) % 4 != 0
            realized_r = 0.8 if positive else -0.4
            signal = start + timedelta(days=index)
            rows.append(
                {
                    "item_id": f"{symbol}-{index}",
                    "symbol": symbol,
                    "signal_time": signal.isoformat(),
                    "feature_available_at": (signal - timedelta(hours=1)).isoformat(),
                    "label_end_time": (signal + timedelta(days=3)).isoformat(),
                    "source_snapshot_id": f"lb-test:{symbol}:{index}",
                    "features": {
                        "model0_total_score": 78.0 if positive else 32.0,
                        "trend_price_vs_ema20_pct": 4.0 if positive else -2.0,
                        "risk_atr_pct_20": 4.0,
                    },
                    "label": {
                        "target": 1.0 if positive else 0.0,
                        "realized_r": realized_r,
                        "forward_return_pct": realized_r,
                        "entry_price": 100.0,
                        "exit_price": 101.0 if positive else 99.0,
                        "stop_price": 98.0,
                        "target_price": 104.0,
                        "commission_bps_per_side": 1.0,
                        "slippage_bps_per_side": 5.0,
                        "target_first": positive,
                        "stop_first": not positive,
                        "sector": "test-sector" if symbol != "CCC" else "other-sector",
                        "market_regime": "risk_on" if index % 2 else "data_caution",
                        "volatility_bucket": "medium",
                    },
                }
            )
    return rows


def _candles(symbol: str, count: int, start: datetime, *, interval: str) -> dict:
    rows = []
    for index in range(count):
        close = 100.0 + index * 0.2
        stamp = start + (timedelta(days=index) if interval == "1d" else timedelta(hours=index))
        rows.append(
            {
                "open_time": stamp.isoformat(),
                "open": close - 0.2,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 100_000 + index,
                "bar_state": "closed_candle",
            }
        )
    return {
        "symbol": symbol,
        "interval": interval,
        "source_type": "longbridge_candles",
        "provider_symbol": f"US.{symbol}",
        "provider_status": "available",
        "candles": rows,
        "adjustment_mode": "unadjusted",
    }


def test_validation_registers_models_without_using_test_for_selection(tmp_path: Path) -> None:
    db_path = tmp_path / "validation.sqlite3"
    dataset = build_stock_quant_dataset(db_path, _items(), dataset_id="stock-validation-test")

    report = run_stock_quant_validation(db_path, dataset["dataset_id"], random_seed=7)

    assert report["read_only_research"] is True
    assert report["summary"]["test_partition_used_for_selection"] is False
    assert report["summary"]["oos_fold_count"] == 3
    assert report["summary"]["overall_gate_checks"]["oos_fold_count_gate"] is True
    assert report["summary"]["gate_status"] == "no_go"
    assert report["summary"]["selected_model_by_train_validation"] in {"model0_rule", "logistic"}
    assert report["summary"]["deployment_model"] is None
    assert report["summary"]["deployment_status"] == "no_eligible_model"
    assert report["summary"]["deployment_blockers"]
    assert report["current_contract_compatible"] is True
    assert {item["model_name"] for item in report["reports"]} >= {"model0_rule", "logistic"}
    for model in report["summary"]["models"]:
        if model["status"] == "verified":
            assert model["test_partition_used_for_selection"] is False
            assert "cost_sensitivity" in model
            assert "concentration" in model
            assert model["walk_forward"]["minimum_fold_count_met"] is True
            assert model["walk_forward"]["sealed_test_partition_used"] is False
            assert "walk_forward_stability" in model["gate_checks"]
            assert "conservative_profit_factor_at_least_1_05" in model["gate_checks"]
            assert "leave_best_five_symbols_positive" in model["gate_checks"]
            assert "single_symbol_profit_contribution_at_most_15pct" in model["gate_checks"]
            assert "calibration_comparison" in model
            assert model["calibration_comparison"]["comparison_partition_used_for_selection"] is False


def test_validation_rejects_yahoo_reference_rows(tmp_path: Path) -> None:
    rows = _items(40)
    rows[0]["source_snapshot_id"] = "yahoo-reference:AAA:0"
    db_path = tmp_path / "yahoo.sqlite3"
    dataset = build_stock_quant_dataset(db_path, rows, dataset_id="stock-yahoo-rejected")

    with pytest.raises(DatasetIntegrityError, match="Yahoo"):
        run_stock_quant_validation(db_path, dataset["dataset_id"])


def test_cache_builder_uses_longbridge_only_and_excludes_forming_bars(tmp_path: Path) -> None:
    db_path = tmp_path / "cache.sqlite3"
    start = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO stock_universe(symbol, name, sector, layer, tags_json, rank, active, updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            ("AAA", "AAA", "Technology", "Core", "[]", 1, start.isoformat()),
        )
        conn.commit()
    for symbol in ("AAA", "SPY", "QQQ"):
        payload = _candles(symbol, 400, start, interval="1d")
        persist_canonical_candles(db_path, payload, (start + timedelta(days=400)).isoformat())
    hourly = _candles("AAA", 80, start - timedelta(hours=80), interval="1h")
    hourly["candles"][-1]["bar_state"] = "forming_candle"
    persist_canonical_candles(db_path, hourly, (start + timedelta(days=400)).isoformat())

    result = build_stock_quant_cache_dataset(db_path, symbols=["AAA"], max_items_per_symbol=40, stride=5)

    assert result["source_policy"] == "longbridge_only_no_yahoo"
    assert result["build"]["items"] > 0
    with connect(db_path) as conn:
        source_ids = [row["source_snapshot_id"] for row in conn.execute("SELECT source_snapshot_id FROM quant_dataset_items")]
    assert source_ids
    assert all("yahoo" not in value.lower() for value in source_ids)


def test_cache_builder_rejects_insufficient_longbridge_history(tmp_path: Path) -> None:
    db_path = tmp_path / "short-cache.sqlite3"
    start = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    with connect(db_path) as conn:
        conn.execute(
            "INSERT INTO stock_universe(symbol, name, sector, layer, tags_json, rank, active, updated_at) VALUES (?, ?, ?, ?, ?, ?, 1, ?)",
            ("AAA", "AAA", "Technology", "Core", "[]", 1, start.isoformat()),
        )
        conn.commit()
    for symbol in ("AAA", "SPY", "QQQ"):
        persist_canonical_candles(db_path, _candles(symbol, 50, start, interval="1d"), (start + timedelta(days=50)).isoformat())
    persist_canonical_candles(db_path, _candles("AAA", 30, start, interval="1h"), (start + timedelta(days=50)).isoformat())

    with pytest.raises(DatasetIntegrityError, match="did not produce"):
        build_stock_quant_cache_dataset(db_path, symbols=["AAA"], max_items_per_symbol=2)
