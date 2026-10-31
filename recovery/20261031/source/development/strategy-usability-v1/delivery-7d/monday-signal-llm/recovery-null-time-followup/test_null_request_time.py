"""A measured clock does not turn a push into a post-boundary pull."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[5] / "source/development/workspace"
sys.path.insert(0, str(BASE))

from kquant import options_one_minute as common
from kquant.options_opening_momentum import load_policy
from kquant.options_opening_trend_recovery import TrendRecoveryLane
from kquant.options_opening_trend_sdk import candle_evidence

OPEN = datetime(2026, 10, 19, 13, 30, tzinfo=UTC)
NOW = OPEN + timedelta(minutes=5, seconds=1)


@pytest.fixture
def decisions(monkeypatch):
    name = "kquant.options_minute_decisions"
    spec = importlib.util.spec_from_file_location(
        name, HERE / "patches/kquant/options_minute_decisions.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setitem(sys.modules, name, module)
    import kquant
    monkeypatch.setattr(kquant, "options_minute_decisions", module, raising=False)
    return module


def native_row(*, push=False):
    opened = OPEN + timedelta(minutes=4)
    requested = None if push else NOW - timedelta(milliseconds=20)
    candle = SimpleNamespace(timestamp=opened, open=100, high=103, low=99,
                             close=102, volume=10, turnover=1000)
    row = dict(symbol="TEST_ONLY", interval="1m", open_at=opened.isoformat(),
        available_at=(opened + timedelta(minutes=1)).isoformat(),
        received_at=NOW.isoformat(), request_started_at=requested.isoformat() if requested else None,
        closed=True, open=100, high=103, low=99, close=102, volume=10, turnover=1000)
    row["sdk_evidence"] = candle_evidence(candle, provider_symbol="TEST_ONLY.US",
        interface="QuoteContext.set_on_candlestick" if push else "QuoteContext.candlesticks",
        received_at=NOW.isoformat(), requested_at=row["request_started_at"],
        clock_evidence=dict(state="VERIFIED_BOUND", uncertainty_ms=50,
            checked_at=(NOW - timedelta(seconds=1)).isoformat(),
            source_hash="TEST_ONLY_MEASUREMENT", test_only=True))
    return row


def test_measured_push_is_ineligible_instead_of_crashing(decisions):
    assert not decisions._local_candidate(native_row(push=True), {"method": decisions.LOCAL_METHOD})


@pytest.mark.parametrize("field,value", [
    ("request_started_at", None), ("request_started_at", 123),
    ("received_at", None), ("available_at", None), ("checked_at", None),
])
def test_invalid_time_is_not_a_usable_pull(decisions, field, value):
    row = deepcopy(native_row())
    if field == "request_started_at":
        row["sdk_evidence"][field] = value
    elif field == "checked_at":
        row["sdk_evidence"]["clock_evidence"][field] = value
    else:
        row[field] = value
    assert not decisions._local_candidate(row, {"method": decisions.LOCAL_METHOD})


def test_valid_pull_and_original_clock_boundary_unchanged(decisions):
    row = native_row()
    assert decisions._local_candidate(row, {"method": decisions.LOCAL_METHOD})
    row["sdk_evidence"]["request_started_at"] = (OPEN + timedelta(minutes=5, milliseconds=20)).isoformat()
    assert not decisions._local_candidate(row, {"method": decisions.LOCAL_METHOD})


@pytest.mark.parametrize("change", ["uncertainty", "expired", "clock_state", "clock_hash",
                                    "future_request", "early_request", "adjustment", "method"])
def test_existing_source_and_time_gates_remain_strict(decisions, change):
    row = native_row()
    proof = {"method": decisions.LOCAL_METHOD}
    clock = row["sdk_evidence"]["clock_evidence"]
    if change == "uncertainty":
        clock["uncertainty_ms"] = 1001
    elif change == "expired":
        clock["checked_at"] = (NOW - timedelta(seconds=902)).isoformat()
    elif change == "clock_state":
        clock["state"] = "UNVERIFIED"
    elif change == "clock_hash":
        clock["source_hash"] = None
    elif change == "future_request":
        row["sdk_evidence"]["request_started_at"] = (NOW + timedelta(seconds=1)).isoformat()
    elif change == "early_request":
        row["sdk_evidence"]["request_started_at"] = OPEN.isoformat()
    elif change == "adjustment":
        row["sdk_evidence"]["adjustment"] = "ForwardAdjust"
    elif change == "method":
        proof = {"method": {**decisions.LOCAL_METHOD, "extend_deadline": True}}
    assert not decisions._local_candidate(row, proof)


def test_real_recovery_observe_keeps_original_deadline(tmp_path, decisions):
    minute = tmp_path / "epoch/minute.sqlite3"
    research = tmp_path / "research/opening.sqlite3"
    minute.parent.mkdir()
    research.parent.mkdir()
    common.initialize(minute)
    lane = TrendRecoveryLane(minute, lambda *unused: pytest.fail("No SDK call expected"),
        queue_path=research, clock=lambda: NOW)
    try:
        row = native_row(push=True)
        opened = common.timestamp(row["open_at"])
        lane.observe("TEST_ONLY", opened, {opened: row}, load_policy(), "TEST_ONLY_SCOPE")
        task = next(iter(lane.pending.values()))
        assert task["deadline_at"] == "2026-10-19T13:40:00+00:00"
        assert row["open_at"] in task["missing_bars"]
        assert len(task["missing_bars"]) == 5
        assert not lane.bar_ready("TEST_ONLY", opened, row)
        assert lane.bar_ready("TEST_ONLY", opened, native_row())
        assert minute.parent != research.parent
    finally:
        lane.close()


def test_actual_worker_push_pull_wakeup_and_s1_with_measured_pushes(tmp_path, monkeypatch, decisions):
    sys.path.insert(0, str(HERE.parents[1]))
    from test_worker_recovery_flow import (
        OneMinuteResearchWorker, test_push_cache_through_worker_pull_durable_wakeup_and_s1)

    original_record = OneMinuteResearchWorker._record

    def measured_push_input(self, row, **kwargs):
        if row.get("sdk_evidence", {}).get("interface") == "QuoteContext.set_on_candlestick":
            row = deepcopy(row)
            row["sdk_evidence"].update(request_started_at=None, clock_evidence=dict(
                state="VERIFIED_BOUND", uncertainty_ms=50,
                checked_at=(self.clock() - timedelta(seconds=1)).isoformat(),
                source_hash="TEST_ONLY_MEASURED_PUSH_CLOCK", test_only=True))
        return original_record(self, row, **kwargs)

    # Only external input shape changes; real Worker/recovery/journal/model remain.
    monkeypatch.setattr(OneMinuteResearchWorker, "_record", measured_push_input)
    test_push_cache_through_worker_pull_durable_wakeup_and_s1(tmp_path, monkeypatch)
