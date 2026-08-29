from __future__ import annotations

from kquant.stock_signals import build_signal, fixture_candles_payload, profile_config


def test_canonical_signal_exposes_data_quality_gate_and_blocks_fixture_buy() -> None:
    daily = fixture_candles_payload("NVDA", "1y", "1d")
    hourly = fixture_candles_payload("NVDA", "5d", "1h")
    daily["data_quality"] = {"status": "blocked", "hard_veto_reasons": ["fixture_data"]}
    hourly["data_quality"] = {"status": "blocked", "hard_veto_reasons": ["fixture_data"]}

    signal = build_signal("NVDA", daily, hourly, profile_config("swing_long_v1"))

    assert signal["data_status"]["data_quality"] == "caution"
    assert "fixture_data" in signal["data_status"]["data_quality_hard_vetoes"]
    assert signal["level"] != "BUY SETUP"
