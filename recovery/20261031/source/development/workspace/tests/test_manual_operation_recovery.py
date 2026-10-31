import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from kquant import options_one_minute as rules
from kquant import options_one_minute_manual as manual
from kquant import options_opening_trend_store as store
from test_r58_positive_chain import prepare


def setup_report(tmp_path, monkeypatch):
    args, evaluation, _, _ = prepare(tmp_path, monkeypatch)
    ledger, research = tmp_path / "manual.sqlite3", tmp_path / "research.sqlite3"
    rules.initialize(ledger)
    store.initialize(research)
    store.persist([evaluation], research)
    payload = dict(operation_key="test-only-open-001", evaluation_id=evaluation["evaluation_id"],
        contract_id="TEST261006C105000.US", quantity=2, multiplier=100, entry_price=1.01,
        underlying_entry_price=105, entry_fees=1, exit_fee_estimate=1,
        executed_at=args["now"].isoformat())
    return ledger, research, payload, args["now"]


def test_cross_store_lookup_holds_no_write_lock(tmp_path, monkeypatch):
    ledger, research, payload, now = setup_report(tmp_path, monkeypatch)
    original = store.detail

    def checked(*args):
        with closing(sqlite3.connect(ledger, timeout=.01)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.rollback()
        return original(*args)

    monkeypatch.setattr(store, "detail", checked)
    result = manual.open_report(payload, reviewer="owner", path=ledger, trend_path=research, now=now)
    assert manual.operation_status(payload["operation_key"], reviewer="owner", path=ledger)["report"] == result
    assert manual.operation_status(payload["operation_key"], reviewer="other", path=ledger)["operation_status"] == "NOT_FOUND"
    with pytest.raises(PermissionError):
        manual.operation_status(payload["operation_key"], reviewer="", path=ledger)


def test_concurrent_duplicate_commits_once(tmp_path, monkeypatch):
    ledger, research, payload, now = setup_report(tmp_path, monkeypatch)
    def submit(_):
        return manual.open_report(payload, reviewer="owner", path=ledger, trend_path=research, now=now)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(submit, range(2)))
    assert results[0] == results[1]
    with closing(sqlite3.connect(ledger)) as connection:
        assert connection.execute("SELECT count(*) FROM one_minute_manual_events").fetchone()[0] == 1
    assert manual.operation_status("test-only-missing", reviewer="owner", path=ledger)["operation_status"] == "NOT_FOUND"
    with pytest.raises(sqlite3.OperationalError):
        manual.operation_status(payload["operation_key"], reviewer="owner", path=tmp_path / "missing.sqlite3")


def test_operation_keeps_original_event_and_reports_current_remaining(tmp_path, monkeypatch):
    ledger, research, payload, now = setup_report(tmp_path, monkeypatch)
    original = manual.open_report(payload, reviewer="owner", path=ledger, trend_path=research, now=now)
    exit_payload = dict(operation_key="test-only-exit-001", position_id=original["position_id"],
                        quantity=1, exit_price=1.1, executed_at=now.isoformat())
    exited = manual.exit_report(exit_payload, reviewer="owner", path=ledger, now=now)
    for key, event in ((payload["operation_key"], original), (exit_payload["operation_key"], exited)):
        status = manual.operation_status(key, reviewer="owner", path=ledger)
        assert status["report"] == event
        assert status["position_snapshot_state"] == "AVAILABLE"
        assert status["current_position"]["open_quantity"] == 1
        assert status["current_position"]["position_id"] == original["position_id"]
    assert original["open_quantity"] == 2
    assert manual.operation_status(payload["operation_key"], reviewer="other", path=ledger) == {
        "operation_key": payload["operation_key"], "operation_status": "NOT_FOUND"}


def test_missing_current_position_does_not_erase_committed_operation(tmp_path, monkeypatch):
    ledger, research, payload, now = setup_report(tmp_path, monkeypatch)
    original = manual.open_report(payload, reviewer="owner", path=ledger, trend_path=research, now=now)
    with closing(sqlite3.connect(ledger)) as connection, connection:
        connection.execute("DELETE FROM one_minute_manual_positions")
    status = manual.operation_status(payload["operation_key"], reviewer="owner", path=ledger)
    assert status["operation_status"] == "COMMITTED"
    assert status["report"] == original
    assert status["current_position"] is None
    assert status["position_snapshot_state"] == "UNAVAILABLE"
