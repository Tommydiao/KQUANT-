"""Isolated price-fact commits; no market or production recovery claims."""
from contextlib import closing, contextmanager
from concurrent.futures import Future
from copy import deepcopy
from datetime import date
import sqlite3
from types import SimpleNamespace

import pytest

from test_r58_p7_inputs import fact_inputs
from kquant import options_one_minute as common
from kquant import options_price_facts as facts
from kquant import options_opening_momentum_journal as journal


def binding(tmp_path, monkeypatch):
    args, quote, reviews = fact_inputs(tmp_path, monkeypatch)
    return facts.bind(quote, symbol="TEST", session="2026-10-02",
                      now=args["now"], reviews=reviews, root=tmp_path)


def test_single_binding_uses_one_connection_for_both_facts(tmp_path, monkeypatch):
    value = binding(tmp_path, monkeypatch)
    path = tmp_path / "TEST_ONLY-atomic.sqlite3"
    journal.initialize(path)
    original = facts.sqlite3.connect
    opened = []

    def connect(*args, **kwargs):
        opened.append(kwargs.get("timeout"))
        return original(*args, **kwargs)

    monkeypatch.setattr(facts.sqlite3, "connect", connect)
    result = facts.persist_binding(path, value)
    assert opened == [.05]
    with closing(original(path)) as db:
        assert db.execute("SELECT COUNT(*) FROM two_hour_jobs").fetchone()[0] == 2
    assert result == facts.prepare_binding(value)


def test_live_fact_producer_uses_existing_writer_guard(tmp_path, monkeypatch):
    from kquant.options_one_minute_runtime import OneMinuteResearchWorker
    args, quote, reviews = fact_inputs(tmp_path, monkeypatch)
    path = tmp_path / "TEST_ONLY-shared-writer.sqlite3"
    journal.initialize(path)
    entered = []

    @contextmanager
    def guard():
        entered.append(True)
        try:
            yield
        finally:
            entered.pop()

    original = facts.persist_bindings
    def checked(path, values):
        assert entered == [True]
        return original(path, values)

    monkeypatch.setattr(facts, "persist_bindings", checked)
    worker = OneMinuteResearchWorker.__new__(OneMinuteResearchWorker)
    worker.trend_lane = SimpleNamespace(path=path, source_root=tmp_path, _journal_guard=guard)
    rows = list(worker._price_fact_quotes([quote], date(2026, 10, 2), args["now"], reviews))
    assert len(rows) == 1 and entered == []


def test_bounded_batch_is_one_commit_and_unchanged_deduplication(tmp_path, monkeypatch):
    value = binding(tmp_path, monkeypatch)
    path = tmp_path / "TEST_ONLY-batch.sqlite3"
    journal.initialize(path)
    original = facts.sqlite3.connect
    calls = []

    def connect(*args, **kwargs):
        calls.append(kwargs.get("timeout"))
        return original(*args, **kwargs)

    monkeypatch.setattr(facts.sqlite3, "connect", connect)
    prepared = facts.persist_bindings(path, [value] * facts.PRICE_FACT_BATCH_BOUND)
    assert calls == [.05]
    assert len(prepared) == facts.PRICE_FACT_BATCH_BOUND
    assert all(row == facts.prepare_binding(value) for row in prepared)
    with closing(original(path)) as db:
        assert db.execute("SELECT COUNT(*) FROM two_hour_jobs").fetchone()[0] == 2
    assert facts.persist_bindings(path, []) == []
    assert calls == [.05]
    with pytest.raises(ValueError, match="BOUND_EXCEEDED"):
        facts.persist_bindings(path, [value] * (facts.PRICE_FACT_BATCH_BOUND + 1))
    assert calls == [.05]


def test_failure_rolls_back_instrument_and_session_binding(tmp_path, monkeypatch):
    value = binding(tmp_path, monkeypatch)
    path = tmp_path / "TEST_ONLY-rollback.sqlite3"
    journal.initialize(path)
    original = facts.persist_prepared_in_transaction
    touched = []

    def fail_after_insert(db, prepared):
        original(db, prepared)
        touched.append(prepared["fact_hash"])
        if len(touched) == 2:
            raise RuntimeError("TEST_ONLY_INTERRUPTED_BEFORE_COMMIT")

    revised = deepcopy(value)
    revised["previous_close"] += .01
    monkeypatch.setattr(facts, "persist_prepared_in_transaction", fail_after_insert)
    with pytest.raises(RuntimeError, match="INTERRUPTED"):
        facts.persist_bindings(path, [value, revised])
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT COUNT(*) FROM two_hour_jobs").fetchone()[0] == 0


def test_missing_store_is_not_created_by_fact_persistence(tmp_path, monkeypatch):
    value = binding(tmp_path, monkeypatch)
    path = tmp_path / "TEST_ONLY-missing-business-store.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        facts.persist_binding(path, value)
    assert not path.exists()


def test_locked_batch_does_not_leave_only_instrument_fact(tmp_path, monkeypatch):
    value = binding(tmp_path, monkeypatch)
    path = tmp_path / "TEST_ONLY-locked.sqlite3"
    journal.initialize(path)
    with closing(sqlite3.connect(path)) as owner:
        owner.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            facts.persist_bindings(path, [value])
        owner.rollback()
        assert owner.execute("SELECT COUNT(*) FROM two_hour_jobs").fetchone()[0] == 0
    result = facts.persist_bindings(path, [value])[0]
    assert facts.valid(result, symbol="TEST", session="2026-10-02",
                       now=common.timestamp(result["known_at"]),
                       root=tmp_path)


def test_actual_preflight_reuses_reviews_and_commits_bounded_groups(tmp_path, monkeypatch):
    from kquant.options_one_minute_runtime import OneMinuteResearchWorker
    from kquant import options_opening_trend_reference as sources

    args, quote, reviews = fact_inputs(tmp_path, monkeypatch)
    path = tmp_path / "TEST_ONLY-preflight.sqlite3"
    journal.initialize(path)
    original_bind, original_persist = facts.bind, facts.persist_bindings
    reviewed, batch_sizes, loads = [], [], []

    def checked_bind(row, **kwargs):
        reviewed.append(kwargs["reviews"])
        assert kwargs["root"] == tmp_path
        return original_bind(row, **kwargs)

    def persist(path, values):
        batch_sizes.append(len(values))
        return original_persist(path, values)

    def load_reviews():
        loads.append(1)
        return reviews

    monkeypatch.setattr(facts, "bind", checked_bind)
    monkeypatch.setattr(facts, "persist_bindings", persist)
    monkeypatch.setattr(sources, "load_reviews", load_reviews)
    target = date.fromisoformat("2026-10-02")
    future = Future()
    # Repeated TEST_ONLY quotes exercise the group boundary, not 33 real assets.
    future.set_result({"items": [deepcopy(quote) for _ in range(33)]})
    worker = OneMinuteResearchWorker.__new__(OneMinuteResearchWorker)
    worker.price_preflight_future, worker.price_preflight_target = future, target
    worker.price_preflight_quotes, worker.price_preflight_source_hash = {}, None
    worker.price_preflight_attempted, worker.risk_quote_future = {target}, None
    worker.trend_lane, worker.state = SimpleNamespace(path=path, source_root=tmp_path), {}
    worker._prepare_price_facts(args["now"])
    assert worker.price_preflight_future is None
    assert worker.state["price_fact_preflight"]["bound_records"] == 33
    assert worker.state["price_fact_preflight"]["verified_records"] == 33
    assert batch_sizes == [16, 16, 1]
    assert len(loads) == 2
    assert all(row is reviews for row in reviewed)
