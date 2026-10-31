"""Durable capture precedes fresh price verification, without relaxing S0."""
from contextlib import closing, contextmanager
from datetime import timedelta
import json
import sqlite3
from threading import current_thread
from time import monotonic, sleep
from types import SimpleNamespace

import pytest

from kquant import options_one_minute as common
from kquant import options_opening_momentum_journal as journal
from kquant import options_price_reference as prices
from kquant.options_opening_trend_runtime import TrendLane
from test_r58_p7_inputs import fact_inputs


def wait_for(predicate, lane):
    until = monotonic() + 6
    while monotonic() < until:
        value = predicate()
        if value:
            return value
        sleep(.01)
    pytest.fail(str(lane.state))


@pytest.mark.parametrize("changed_source", [False, True])
def test_actual_capture_compute_cas_and_source_change(tmp_path, monkeypatch, changed_source):
    args, quote, reviews = fact_inputs(tmp_path, monkeypatch)
    review_path = tmp_path / "TEST_ONLY-sources.json"
    review_path.write_text(json.dumps(reviews), encoding="utf-8")
    minute = tmp_path / "TEST_ONLY-minute.sqlite3"
    research = tmp_path / "TEST_ONLY-research.sqlite3"
    common.initialize(minute)
    common.save_bars(args["bars"], "2026-10-02", minute)
    calls, events, admitted = [], [], []
    original_build, original_ready = prices.build, journal.ready_many
    from kquant import bounded_sqlite
    original_read = bounded_sqlite.read_connection
    active_reads = {}

    @contextmanager
    def observed_read(path, **keywords):
        name = current_thread().name
        with original_read(path, **keywords) as db:
            active_reads[name] = active_reads.get(name, 0) + 1
            try:
                yield db
            finally:
                active_reads[name] -= 1

    def observed_build(*arguments, **keywords):
        calls.append(current_thread().name)
        assert not active_reads.get(current_thread().name), "source checks must not consume the SQL budget"
        return original_build(*arguments, **keywords)

    def observed_ready(path, entries):
        outcome = original_ready(path, entries)
        if any(outcome) and not admitted:
            with closing(sqlite3.connect(path)) as db:
                raw = db.execute("SELECT payload_json FROM two_hour_jobs WHERE slot='1'").fetchone()[0]
            admitted.append(json.loads(raw))
            if changed_source:
                source = tmp_path / "test-fact.txt"
                raw = source.read_bytes()
                source.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        return outcome

    monkeypatch.setattr(prices, "build", observed_build)
    monkeypatch.setattr(journal, "ready_many", observed_ready)
    monkeypatch.setattr(bounded_sqlite, "read_connection", observed_read)
    lane = TrendLane(minute, SimpleNamespace(publish=events.append), path=research,
        clock=lambda: args["now"], source_root=tmp_path, source_reviews_path=review_path)
    try:
        lane.enqueue("TEST", args["opening"].date(), [], args["scope_hash"], {"raw_quote": quote})
        target = "WAIT_INPUT" if changed_source else "COMPLETED"

        def current_job():
            with closing(sqlite3.connect(research, timeout=.1)) as db:
                row = db.execute("SELECT state,deadline_at,payload_json FROM two_hour_jobs WHERE slot='1'").fetchone()
                rows = db.execute("SELECT state FROM evaluations").fetchall()
            return (row, rows) if row and row[0] == target and rows else None

        row, rows = wait_for(current_job, lane)
        assert admitted[0]["reference"] == {"raw_quote": quote}
        assert row[1] == (args["opening"] + timedelta(minutes=10)).isoformat()
        assert "opening-checkpoint-journal" not in calls
        assert "opening-trend-research" in calls
        assert json.loads(row[2])["input_generation"] >= 2
        if changed_source:
            assert {state for state, in rows} == {"INCOMPLETE"}
        else:
            assert {state for state, in rows} == {"NUMERIC_PASS", "NO_TRIGGER"}
        with closing(sqlite3.connect(research)) as db:
            assert db.execute("SELECT COUNT(*) FROM qualified_claims").fetchone()[0] == 0
    finally:
        lane.close()


def test_prefetched_versions_are_batch_scoped_and_read_again(tmp_path, monkeypatch):
    from copy import deepcopy
    from threading import local
    from kquant import bounded_sqlite
    from test_options_opening_momentum import inputs
    args = inputs()
    session = args["opening"].date()
    minute = tmp_path / "TEST_ONLY-minute.sqlite3"
    common.initialize(minute)
    common.save_bars(args["bars"], session.isoformat(), minute)
    lane = TrendLane.__new__(TrendLane)
    lane.minute_path, lane.path = minute, tmp_path / "UNOPENED-research.sqlite3"
    lane.input_read_context, lane.timings = local(), {}
    key = "opening_momentum", session.isoformat(), args["symbol"], 1
    job = args["symbol"], session, [], "scope", {}
    original = bounded_sqlite.read_connection
    opened, active = [], []

    @contextmanager
    def counted(path, **keywords):
        opened.append(keywords["seconds"])
        with original(path, **keywords) as db:
            active.append(db)
            try:
                yield db
            finally:
                active.pop()

    monkeypatch.setattr(bounded_sqlite, "read_connection", counted)
    with lane._input_batch(entries=[(key, job)]):
        assert not active
        first, _ = lane._checkpoint_inputs(key, job, args["now"], {})
        changed = deepcopy(args["bars"][0])
        changed["close"] -= .01
        common.save_bars([changed], session.isoformat(), minute)
        same_batch, _ = lane._checkpoint_inputs(key, job, args["now"], {})
        assert common.digest(same_batch[2]) == common.digest(first[2])
    assert lane.input_read_context.versions is None
    with lane._input_batch(entries=[(key, job)]):
        second, _ = lane._checkpoint_inputs(key, job, args["now"], {})
        assert len(second[2]) == len(first[2]) + 1
        assert common.digest(second[2]) != common.digest(first[2])
    assert opened == [.3, .3]
    assert lane.timings[key]["input_batch_read_seconds"] >= 0
    with pytest.raises(ValueError, match="CHECKPOINT_INPUT_BATCH_BOUND_EXCEEDED"):
        with lane._input_batch(entries=[(key, job)] * 17):
            pytest.fail("oversized input batches must not be opened")
    assert opened == [.3, .3]
    assert not lane.path.exists()


def test_original_expired_capture_cannot_be_reopened(tmp_path):
    from test_r58_p7_inputs import setup_job
    path, args, key, job = setup_job(tmp_path)
    deadline = args["opening"] + timedelta(minutes=10)
    fingerprint = journal.input_fingerprint(job)
    assert not journal.ready(path, key, job, deadline, fingerprint=fingerprint)
    changed = (*job[:4], {"raw_quote": {"previous_close": 101}})
    assert not journal.ready(path, key, changed, deadline + timedelta(seconds=1))
    assert journal.begin(path, key, changed, deadline + timedelta(seconds=1)) is None
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT state,deadline_at FROM two_hour_jobs").fetchone() == (
            "EXPIRED", deadline.isoformat())


def test_missing_comparison_excluded_without_dropping_active_checkpoint_and_recovers(tmp_path, monkeypatch):
    from collections import OrderedDict
    from threading import Condition
    from kquant import options_opening_trend as comparison
    from test_options_opening_momentum import inputs
    args = inputs()
    policy_path = tmp_path / "TEST_ONLY-comparison.json"
    monkeypatch.setattr(comparison, "CONFIG", policy_path)
    lane = TrendLane.__new__(TrendLane)
    lane.clock = lambda: args["opening"] + timedelta(minutes=15, seconds=1)
    lane.lock = Condition()
    lane.pending, lane.incoming = OrderedDict(), OrderedDict()
    lane.latest_inputs, lane.checkpoints, lane.waiting = {}, {}, {}
    lane.input_epochs, lane.timings, lane.state = {}, {}, {"coalesced": 0}
    lane.history = SimpleNamespace(request=lambda *a, **kw: None)
    job = "TEST", args["opening"].date(), [], args["scope_hash"], args["reference"]
    lane.enqueue(*job)
    key = "opening_momentum", "2026-10-02", "TEST", 3
    assert key in lane.incoming
    assert not lane.pending
    assert lane.state["strategies"]["opening_trend"]["reason"] == "POLICY_CONFIG_MISSING"
    policy = dict(policy_id=comparison.POLICY_ID, qualified_publication_enabled=False,
        paper_enabled=False, automatic_paper_enabled=False, real_orders_enabled=False, llm_required=False)
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    lane.enqueue(*job)
    assert ("opening_trend", *key[1:]) in lane.pending
    assert lane.state["strategies"]["opening_trend"]["state"] == "READY"
    lane.pending.clear()
    policy["real_orders_enabled"] = True
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    lane.enqueue(*job)
    assert not lane.pending
    assert key in lane.incoming
    assert lane.state["strategies"]["opening_trend"]["reason"] == "POLICY_CONFIG_INVALID"
