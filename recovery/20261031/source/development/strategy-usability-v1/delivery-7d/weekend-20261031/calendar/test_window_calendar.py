from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pytest

DELIVERY = Path(__file__).resolve().parents[2]
WORKSPACE = DELIVERY.parents[1] / "workspace"
sys.path[:0] = [str(WORKSPACE), str(DELIVERY / "opening-first-hour")]
from window_calendar import (budget_date, expected_positions, manual_exit, position_id,
                             reconcile, seconds_remaining, window)

DENOMINATOR = json.loads((DELIVERY / "denominator.json").read_text(encoding="utf-8-sig"))
POLICY = json.loads((WORKSPACE / "config/options_opening_momentum_v1.json").read_text(encoding="utf-8"))
NY = ZoneInfo("America/New_York")


@pytest.mark.parametrize("day,opening", [("2026-03-06", "22:30"), ("2026-03-09", "21:30"),
                                        ("2026-10-30", "21:30"), ("2026-11-02", "22:30")])
def test_installed_project_calendar_dst(day, opening):
    result = window(date.fromisoformat(day), DENOMINATOR)
    assert result["opening"]["display"][11:16] == opening
    assert result["opening"]["exchange"][11:16] == "09:30"
    assert result["checkpoint_count"] == 11
    assert result["positions_per_variant"] == 2200
    assert result["registered"] == 111 and result["unresolved"] == 11
    assert result["identity_unresolved_positions_per_variant"] == 242
    assert not result["scheduled_or_registered"]


def test_monday_all_times_deadlines_and_idempotent_positions():
    day = date(2026, 11, 2)
    result = window(day, DENOMINATOR)
    assert result["prewarm"]["display"].startswith("2026-11-02T21:30:00")
    assert result["readiness"]["display"].startswith("2026-11-02T22:25:00")
    assert result["cutoff"]["display"].startswith("2026-11-02T23:30:00")
    assert result["reconciliation_at"] == result["cutoff"]
    assert result["checkpoints"][0]["at"]["display"].startswith("2026-11-02T22:35:00")
    assert result["checkpoints"][-1]["at"]["display"].startswith("2026-11-02T23:25:00")
    for cp in result["checkpoints"]:
        assert datetime.fromisoformat(cp["deadline"]["utc"]) - datetime.fromisoformat(cp["at"]["utc"]) == timedelta(seconds=300)
    s0 = expected_positions(day, DENOMINATOR, "S0-FIRST-HOUR")
    s1 = expected_positions(day, DENOMINATOR, "S1-FIRST-HOUR")
    assert len(s0) == len(s1) == 2200 and not s0 & s1
    assert s0 == expected_positions(day, DENOMINATOR, "S0-FIRST-HOUR")


@pytest.mark.parametrize("day", [date(2026, 3, 8), date(2026, 11, 1), date(2026, 11, 26)])
def test_closed_day_has_no_tasks(day):
    result = window(day, DENOMINATOR)
    assert result["state"] == "MARKET_CLOSED" and result["positions_per_variant"] == 0
    assert expected_positions(day, DENOMINATOR, "S0") == set()


def test_repeated_hour_does_not_reset_budget_or_duplicate_session_tasks():
    first = datetime(2026, 11, 1, 1, 30, tzinfo=NY, fold=0)
    second = datetime(2026, 11, 1, 1, 30, tzinfo=NY, fold=1)
    assert second.astimezone(UTC) - first.astimezone(UTC) == timedelta(hours=1)
    for zone in ("Asia/Shanghai", "America/New_York"):
        assert budget_date(first, zone) == budget_date(second, zone) == "2026-11-01"
    args = dict(session="2026-11-02", strategy_version="S0", symbol="GWH", right="CALL", scope_hash=DENOMINATOR["scope_hash"])
    cp = datetime(2026, 11, 2, 9, 35, tzinfo=NY)
    assert position_id(checkpoint=cp, **args) == position_id(checkpoint=cp.astimezone(UTC), **args)
    assert expected_positions(first.date(), DENOMINATOR, "S0") == expected_positions(second.date(), DENOMINATOR, "S0") == set()


def test_budget_bjt_midnight_and_countdown_use_instants():
    assert budget_date(datetime(2026, 11, 1, 15, 59, 59, tzinfo=UTC)) == "2026-11-01"
    assert budget_date(datetime(2026, 11, 1, 16, tzinfo=UTC)) == "2026-11-02"
    first = datetime(2026, 11, 1, 1, 30, tzinfo=NY, fold=0)
    second = datetime(2026, 11, 1, 1, 30, tzinfo=NY, fold=1)
    assert seconds_remaining(second, first) == 3600
    assert seconds_remaining(first, second) == 0
    with pytest.raises(ValueError, match="AWARE_INSTANT"):
        budget_date(datetime(2026, 11, 1, 1, 30))


@pytest.mark.parametrize("day,expected", [(date(2026, 10, 30), "2026-10-31T01:30"),
                                          (date(2026, 11, 2), "2026-11-03T01:30"),
                                          (date(2026, 11, 27), "2026-11-28T01:30")])
def test_fixed_bjt_bedtime_vs_four_hours_and_close(day, expected):
    entered = datetime(day.year, day.month, day.day, 9, 35, tzinfo=NY)
    result = manual_exit(day, entered, POLICY)
    # Summer 09:35 + four hours = BJT 01:35, so fixed bedtime is earlier too.
    assert result["planned_exit_at"]["display"].startswith(expected)


def test_early_close_and_short_holding_rule_are_not_shifted():
    result = window(date(2026, 11, 27), DENOMINATOR)
    assert result["early_close"] and result["closing"]["exchange"][11:16] == "13:00"
    summer = manual_exit(date(2026, 10, 30), datetime(2026, 10, 30, 9, 35, tzinfo=NY), POLICY)
    winter = manual_exit(date(2026, 11, 2), datetime(2026, 11, 2, 9, 35, tzinfo=NY), POLICY)
    assert summer["planned_exit_at"]["display"][11:16] == winter["planned_exit_at"]["display"][11:16] == "01:30"
    assert summer["wind_down_at"]["display"][11:16] == winter["wind_down_at"]["display"][11:16] == "01:15"


def test_revisions_do_not_change_denominator_or_invent_system_loss():
    expected = expected_positions(date(2026, 11, 2), DENOMINATOR, "S1")
    key = sorted(expected)[0]
    rows = [{"position_id": key, "revision": 0, "state": "WAIT_INPUT"},
            {"position_id": key, "revision": 1, "state": "COMPLETE"}]
    result = reconcile(expected, rows)
    assert result["expected"] == 2200 and result["recorded_positions"] == 1
    assert result["outcomes"]["COMPLETE"] == 1 and result["missing_evidence_positions"] == 2199
    assert result["unattributed_system_omission_count"] is None
    assert result["outcomes"]["ATTRIBUTED_SYSTEM_OMISSION"] == 0
    with pytest.raises(ValueError, match="CONFLICTING_SAME_REVISION"):
        reconcile(expected, rows + [{"position_id": key, "revision": 1, "state": "DATA_BLOCKED"}])
