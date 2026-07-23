from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from kquant.strategy_validation import bootstrap_mean_interval, walk_forward_split
from kquant.validation_service import (
    api_strategy_validation_action,
    api_strategy_validation_latest,
    run_strategy_validation,
)


def _candles(count: int = 340, interval_hours: int = 24) -> list[dict]:
    start = datetime(2024, 1, 2, 14, 30, tzinfo=UTC)
    rows = []
    price = 80.0
    for index in range(count):
        price += 0.12 + (0.8 if index % 24 == 0 else 0)
        stamp = start + timedelta(hours=index * interval_hours)
        rows.append(
            {
                "open_time": stamp.isoformat(),
                "time": int(stamp.timestamp()),
                "open": price - 0.1,
                "high": price + 1.1,
                "low": price - 0.8,
                "close": price,
                "volume": 2_000_000 if index % 24 == 0 else 1_000_000,
                "bar_state": "closed_candle",
            }
        )
    return rows


def test_walk_forward_split_applies_embargo() -> None:
    items = [{"signal_time": f"2026-01-{index + 1:03d}"} for index in range(100)]
    split = walk_forward_split(items, embargo_bars=5)
    assert [len(split[key]) for key in ("train", "validation", "test")] == [55, 10, 15]


def test_bootstrap_interval_is_deterministic() -> None:
    first = bootstrap_mean_interval([-1, -0.5, 1, 2, 2.5], samples=500, seed=7)
    second = bootstrap_mean_interval([-1, -0.5, 1, 2, 2.5], samples=500, seed=7)
    assert first == second
    assert first[0] < first[1]


def test_validation_run_persists_separate_historical_evidence(tmp_path: Path, monkeypatch) -> None:
    daily = _candles()
    hourly = _candles(count=500, interval_hours=1)

    def fake_universe(universe: str, db_path: Path):
        return {"stocks": [{"symbol": "NVDA", "sector": "Technology", "layer": "Chips"}]}

    def fake_candles(symbol: str, range_value: str, interval: str, source: str, db_path: Path):
        rows = hourly if interval == "1h" else daily
        return {"symbol": symbol, "source_type": "longbridge_candles", "provider_status": "available", "candles": rows}

    monkeypatch.setattr("kquant.stock_signals.api_stock_universe", fake_universe)
    monkeypatch.setattr("kquant.stock_signals.api_stock_candles", fake_candles)
    db_path = tmp_path / "validation.sqlite3"
    payload = run_strategy_validation(
        profiles=["high_beta_growth_v1"], start=None, end=None,
        universe="default", symbols=["NVDA"], db_path=db_path, outputs_dir=tmp_path / "outputs",
    )
    assert payload["evidence_source"] == "historical_policy_replay"
    assert payload["summary"]["sample_count"] > 0
    assert payload["universe_point_in_time"]["survivorship_limited"] is True
    assert payload["data_limitations"]
    latest = api_strategy_validation_latest(db_path, "high_beta_growth_v1")
    assert latest["evidence_mixed"] is False
    assert latest["evidence"]["historical_policy_replay"]["summary"]["sample_count"] > 0
    action = api_strategy_validation_action("AI_PROBE_BUY", db_path, "high_beta_growth_v1")
    assert action["prospective_llm_actions"]["sample_count"] == 0
