from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from kquant.options_radar_supervisor import OptionRadarSupervisor
from kquant.realtime_instructions import AlertEventHub


def test_supervisor_waits_until_0830_and_runs_premarket_once(tmp_path: Path, monkeypatch) -> None:
    calls = []
    monkeypatch.setattr("kquant.options_radar_supervisor.market_schedule", lambda *args, **kwargs: {"is_trading_day": True, "regular_close_utc": "2026-09-14T20:00:00+00:00"})
    monkeypatch.setattr("kquant.options_radar_supervisor.latest_premarket_report", lambda *args, **kwargs: {"status": "not_run" if not calls else "completed"})
    monkeypatch.setattr("kquant.options_radar_supervisor.run_premarket_radar", lambda *args, **kwargs: calls.append("premarket") or {"run_id": "run-1", "opportunities": []})
    monkeypatch.setattr("kquant.options_radar_supervisor.refresh_intraday_radar", lambda *args, **kwargs: {"status": "completed", "updated": 0})
    supervisor = OptionRadarSupervisor(tmp_path / "stock.sqlite3", AlertEventHub())

    early = supervisor.cycle_once(datetime(2026, 9, 14, 12, 29, tzinfo=UTC))
    first = supervisor.cycle_once(datetime(2026, 9, 14, 12, 31, tzinfo=UTC))
    second = supervisor.cycle_once(datetime(2026, 9, 14, 12, 32, tzinfo=UTC))

    assert early["reason"] == "before_0830_et"
    assert first["actions"][0]["type"] == "premarket"
    assert second["actions"] == []
    assert calls == ["premarket"]
