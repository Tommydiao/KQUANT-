from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from kquant.dashboard.app import create_app
from kquant.config import KquantConfig
from kquant.stock_quant import (
    MODEL_0_VERSION,
    build_stock_quant_dataset,
    build_stock_quant_item,
    build_model0_features,
    build_model0_label,
)


def _bars(count: int, *, base: float = 100.0, start: datetime | None = None) -> list[dict]:
    origin = start or datetime(2025, 1, 2, 14, 30, tzinfo=UTC)
    rows = []
    for index in range(count):
        close = base + index * 0.18 + (index % 7) * 0.12
        rows.append(
            {
                "open_time": (origin + timedelta(days=index)).isoformat(),
                "open": close - 0.2,
                "high": close + 1.0 + (index % 3) * 0.1,
                "low": close - 1.0,
                "close": close,
                "volume": 100_000 + (index % 5) * 10_000,
                "bar_state": "closed_candle",
            }
        )
    return rows


def test_model0_future_bars_do_not_change_a_past_snapshot() -> None:
    daily = _bars(245)
    confirmation = _bars(30, start=datetime(2025, 8, 1, 14, 30, tzinfo=UTC))
    as_of = daily[220]["open_time"]
    first = build_model0_features("RKLB", daily[:221], confirmation, as_of_time=as_of)
    second = build_model0_features("RKLB", daily, confirmation, as_of_time=as_of)

    assert first["model_version"] == MODEL_0_VERSION
    assert first["feature_snapshot_hash"] == second["feature_snapshot_hash"]
    assert first["values"] == second["values"]
    assert all(item["as_of_time"] <= as_of for item in first["factors"] if item["as_of_time"])


def test_model0_realtime_and_replay_paths_are_identical_for_same_input() -> None:
    daily = _bars(240)
    confirmation = _bars(25, start=datetime(2025, 8, 1, 14, 30, tzinfo=UTC))
    as_of = daily[-1]["open_time"]
    realtime = build_model0_features("NVDA", daily, confirmation, as_of_time=as_of, source="longbridge_candles")
    replay = build_model0_features("NVDA", daily[:], confirmation[:], as_of_time=as_of, source="longbridge_candles")

    assert realtime["feature_snapshot_hash"] == replay["feature_snapshot_hash"]
    assert realtime["score"] == replay["score"]
    assert realtime["eligibility"]["eligible"] is True


def test_model0_label_enters_on_next_bar_and_stop_wins_same_bar() -> None:
    rows = [
        {"open_time": "2026-01-01T14:30:00+00:00", "open": 99, "high": 101, "low": 98, "close": 100, "volume": 100, "bar_state": "closed_candle"},
        {"open_time": "2026-01-02T14:30:00+00:00", "open": 100, "high": 110, "low": 90, "close": 102, "volume": 100, "bar_state": "closed_candle"},
        {"open_time": "2026-01-03T14:30:00+00:00", "open": 102, "high": 103, "low": 101, "close": 102, "volume": 100, "bar_state": "closed_candle"},
    ]
    label = build_model0_label(rows, signal_index=0, stop_price=95, target_price=105, horizon_bars=2)

    assert label["completed"] is True
    assert label["entry_index"] == 1
    assert label["entry_time"] == rows[1]["open_time"]
    assert label["outcome"] == "same_bar_stop_first"
    assert label["stop_first"] is True
    assert label["target_first"] is False


def test_model0_label_uses_actual_gap_open_for_stop() -> None:
    rows = [
        {"open_time": "2026-01-01T14:30:00+00:00", "open": 99, "high": 101, "low": 98, "close": 100, "volume": 100, "bar_state": "closed_candle"},
        {"open_time": "2026-01-02T14:30:00+00:00", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 100, "bar_state": "closed_candle"},
        {"open_time": "2026-01-03T14:30:00+00:00", "open": 90, "high": 92, "low": 88, "close": 91, "volume": 100, "bar_state": "closed_candle"},
        {"open_time": "2026-01-04T14:30:00+00:00", "open": 91, "high": 93, "low": 90, "close": 92, "volume": 100, "bar_state": "closed_candle"},
    ]
    label = build_model0_label(rows, signal_index=0, stop_price=95, target_price=105, horizon_bars=3)

    assert label["outcome"] == "gap_stop"
    assert label["exit_price"] < 90


def test_stock_quant_dataset_seals_model0_feature_and_label_audit(tmp_path: Path) -> None:
    daily = _bars(390)
    confirmation = _bars(40, start=datetime(2025, 1, 2, 14, 30, tzinfo=UTC))
    items = [
        build_stock_quant_item(
            "RKLB",
            daily,
            confirmation,
            signal_index=220 + index * 5,
            stop_price=daily[220 + index * 5]["close"] - 2.0,
            target_price=daily[220 + index * 5]["close"] + 4.0,
            source_snapshot_id=f"snapshot-{index}",
            horizon_bars=3,
        )
        for index in range(30)
    ]
    result = build_stock_quant_dataset(tmp_path / "quant.sqlite3", items, dataset_id="stock-model0-fixed")

    assert result["status"] == "sealed"
    assert result["model_version"] == MODEL_0_VERSION
    assert result["feature_count"] == result["label_count"]
    assert result["feature_count"] > 0


def test_stock_quant_api_is_read_only_and_empty_before_dataset(tmp_path: Path) -> None:
    app = create_app(config=KquantConfig(db_path=tmp_path / "kquant.sqlite3", outputs_dir=tmp_path / "outputs"))
    client = TestClient(app)

    ranking = client.get("/api/quant/stocks/ranking")
    detail = client.get("/api/quant/stocks/RKLB")

    assert ranking.status_code == 200
    assert ranking.json()["status"] == "not_materialized"
    assert detail.status_code == 200
    assert detail.json()["status"] == "not_materialized"
