from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from kquant import options_one_minute_runtime as runtime
from kquant import options_opening_trend_reference as reference
from kquant import options_opening_trend_store as store
from test_strategy_usability import inputs, pair


def test_prepared_results_are_detached_before_writer_transaction():
    rows = pair(inputs())
    prepared = store.prepare_evaluations(rows)
    original = prepared.rows[0]["state"]
    rows[0]["state"] = "MUTATED_AFTER_CAPTURE"
    assert prepared.rows[0]["state"] == original
    assert store.prepare_evaluations(prepared) is prepared
    assert len(prepared.values) == 4


def test_busy_fact_rebind_preserves_quotes_and_recovers_without_provider(monkeypatch):
    now = datetime(2026, 10, 15, 13, 0, tzinfo=UTC)
    day = now.date()
    quotes = [{"symbol": "TEST"}]
    worker = SimpleNamespace(price_preflight_future=None,
        price_preflight_quotes={day: quotes}, price_preflight_source_hash="old",
        price_preflight_attempted={day}, risk_quote_future=None, state={})
    calls = []

    def binding(rows, target, stamp, reviews):
        calls.append((rows, target))
        if len(calls) == 1:
            raise TimeoutError("CHECKPOINT_INTERNAL_WRITER_BUSY")
        return [(rows[0], {"status": "PREPARED_WITH_GAPS", "reasons": ["MISSING_PROOF"]})]

    worker._price_fact_quotes = binding
    monkeypatch.setattr(reference, "load_reviews", lambda: {"source_bundle": {"sha256": "new"}})
    runtime.OneMinuteResearchWorker._prepare_price_facts(worker, now)
    assert worker.state["price_fact_preflight"]["stage"] == "WAIT_PERSIST"
    assert worker.price_preflight_source_hash == "old"
    assert worker.price_preflight_quotes[day] is quotes
    runtime.OneMinuteResearchWorker._prepare_price_facts(worker, now + timedelta(milliseconds=500))
    assert len(calls) == 1
    runtime.OneMinuteResearchWorker._prepare_price_facts(worker, now + timedelta(seconds=1))
    assert len(calls) == 2
    assert worker.price_preflight_source_hash == "new"
    assert not worker.price_preflight_write_pending


def test_fact_retry_exhaustion_is_bounded_and_source_change_rearms(monkeypatch):
    now = datetime(2026, 10, 15, 13, 0, tzinfo=UTC)
    day = now.date()
    source = {"source_bundle": {"sha256": "new"}}
    worker = SimpleNamespace(price_preflight_future=None,
        price_preflight_quotes={day: [{"symbol": "TEST"}]}, price_preflight_source_hash="old",
        price_preflight_attempted={day}, risk_quote_future=None, state={})
    calls = []

    def busy(*args):
        calls.append(1)
        raise TimeoutError("CHECKPOINT_INTERNAL_WRITER_BUSY")

    worker._price_fact_quotes = busy
    monkeypatch.setattr(reference, "load_reviews", lambda: source)
    for second in range(5):
        runtime.OneMinuteResearchWorker._prepare_price_facts(worker, now + timedelta(seconds=second))
    assert len(calls) == 3
    assert worker.state["price_fact_preflight"]["stage"] == "PERSIST_RETRY_EXHAUSTED"
    source["source_bundle"]["sha256"] = "changed"
    runtime.OneMinuteResearchWorker._prepare_price_facts(worker, now + timedelta(seconds=6))
    assert len(calls) == 4
