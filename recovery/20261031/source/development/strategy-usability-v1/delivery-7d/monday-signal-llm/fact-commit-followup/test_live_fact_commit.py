"""Actual Worker construction, read-only preparation and atomic journal commit."""
from contextlib import closing, contextmanager, nullcontext
from concurrent.futures import Future
from copy import deepcopy
from datetime import timedelta
import importlib.util
from pathlib import Path
import queue
import sqlite3
import sys
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parents[1]
BASE = HERE.parents[4] / "source/development/workspace"
sys.path[:0] = [str(BASE), str(BASE / "tests")]
from kquant import options_one_minute as common
from kquant import options_opening_trend_store as store
from kquant import options_opening_momentum_journal as journal
from kquant import options_price_facts as facts
from test_r58_p7_inputs import fact_inputs

spec = importlib.util.spec_from_file_location("kquant._test_live_fact_commit",
    HERE / "fact-commit-followup/patches/kquant/options_one_minute_runtime.py")
subject = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = subject
spec.loader.exec_module(subject)


@pytest.fixture
def constructed(tmp_path, monkeypatch):
    for key in ("KQUANT_RUNTIME_DATA_ROOT", "KQUANT_RUNTIME_PATH_BINDING", "KQUANT_RUNTIME_PATH_BINDING_SHA256"):
        monkeypatch.delenv(key, raising=False)
    args, quote, reviews = fact_inputs(tmp_path, monkeypatch)
    research = tmp_path / "research/TEST_ONLY.sqlite3"
    research.parent.mkdir()
    minute = tmp_path / "epoch/TEST_ONLY.sqlite3"
    minute.parent.mkdir()
    store.initialize(research)
    journal.initialize(research)
    worker = subject.OneMinuteResearchWorker(tmp_path / "unused-main.sqlite3",
        SimpleNamespace(publish=lambda event: None), path=minute,
        runtime=SimpleNamespace(event_queue=lambda *args, **kwargs: queue.Queue()), clock=lambda: args["now"])
    worker.trend_lane = SimpleNamespace(path=research, source_root=tmp_path, _journal_guard=nullcontext)
    quote["symbol"] = "TEST"
    try:
        yield worker, args, quote, reviews, research
    finally:
        worker.provider_jobs.shutdown(wait=True, cancel_futures=True)
        worker.risk_jobs.shutdown(wait=True, cancel_futures=True)


def fact_count(path):
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True)) as db:
        return db.execute("SELECT count(*) FROM two_hour_jobs WHERE slot IN (?,?)",
            (facts.BINDING, facts.INSTRUMENT)).fetchone()[0]


def test_live_prepare_avoids_busy_guard_but_prewarm_remains_fail_closed(constructed):
    worker, args, quote, reviews, path = constructed

    @contextmanager
    def busy():
        raise TimeoutError("TEST_ONLY_EXISTING_JOURNAL_BUSY")
        yield

    worker.trend_lane._journal_guard = busy
    values = list(worker._price_fact_quotes([quote], args["opening"].date(), args["now"], reviews, persist=False))
    assert values[0][1]["fact_hash"] == common.digest({k: v for k, v in values[0][1].items() if k != "fact_hash"})
    assert fact_count(path) == 0
    with pytest.raises(TimeoutError, match="JOURNAL_BUSY"):
        list(worker._price_fact_quotes([quote], args["opening"].date(), args["now"], reviews))
    assert fact_count(path) == 0
    worker.trend_lane._journal_guard = nullcontext
    saved = list(worker._price_fact_quotes([quote], args["opening"].date(), args["now"], reviews))
    assert saved[0][1] == values[0][1]
    assert fact_count(path) == 2


def test_live_refresh_selects_prepare_without_sdk_or_early_write(constructed, monkeypatch):
    worker, args, quote, reviews, path = constructed
    from kquant import options_opening_trend_reference
    monkeypatch.setattr(options_opening_trend_reference, "load_reviews", lambda: reviews)
    worker.day = args["opening"].date()
    worker.provider_by_symbol = {"TEST": "TEST.US"}
    worker.next_trend_reference_at = args["now"]+timedelta(minutes=1)
    received = []
    worker.trend_lane.reference_ready = lambda *values: received.append(values)
    worker.trend_reference_future = Future()
    worker.trend_reference_future.set_result(dict(items=[quote]))

    @contextmanager
    def unexpected_guard():
        pytest.fail("Live refresh must not acquire the preflight journal guard")
        yield

    worker.trend_lane._journal_guard = unexpected_guard
    worker._refresh_trend_references(args["now"])
    assert len(received) == 1
    assert received[0][0] == "TEST"
    assert fact_count(path) == 0
    assert worker.trend_reference_future is None
    assert worker.state["trend_reference"]["received_symbols"] == 1


def test_stale_cas_cannot_persist_prepared_facts_and_accepted_cas_is_atomic(constructed):
    worker, args, quote, reviews, path = constructed
    _, binding = next(worker._price_fact_quotes([quote], args["opening"].date(), args["now"], reviews, persist=False))
    key = "opening_momentum", args["opening"].date().isoformat(), "TEST", 1
    job = "TEST", args["opening"].date(), deepcopy(args["bars"]), "TEST_ONLY_SCOPE", {"raw_quote": quote}
    assert journal.ready(path, key, job, args["now"])
    old = journal.begin(path, key, job, args["now"])
    newer = deepcopy(job)
    newer[2][0]["close"] += .001
    assert journal.ready(path, key, newer, args["now"])
    result = dict(evaluation_id="TEST_ONLY_FACT_COMMIT", policy_hash="TEST_ONLY_POLICY",
        session=key[1], symbol="TEST", right="CALL", evaluated_at=args["now"].isoformat(),
        state="INCOMPLETE", reference_evidence={"session_price_binding": binding})
    prepared = store.prepare_evaluations([result])
    assert journal.finish_many(path, [(old, True, prepared)]) == [False]
    assert fact_count(path) == 0
    lease = journal.begin(path, key, newer, args["now"])
    assert journal.finish_many(path, [(lease, True, prepared)]) == [True]
    assert fact_count(path) == 2
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro", uri=True)) as db:
        assert db.execute("SELECT count(*) FROM evaluations").fetchone()[0] == 1
