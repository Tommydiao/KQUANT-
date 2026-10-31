"""A fresh program-built binding is checked once, then revalidated by S0."""
from datetime import timedelta

from test_r58_p7_inputs import fact_inputs
from kquant import options_price_facts as facts
from kquant import options_price_reference as prices


def test_fresh_build_does_not_immediately_rebuild_and_valid_rechecks(tmp_path, monkeypatch):
    args, quote, reviews = fact_inputs(tmp_path, monkeypatch)
    original = facts.bind
    calls = []

    def observed(*arguments, **keywords):
        calls.append(keywords)
        return original(*arguments, **keywords)

    monkeypatch.setattr(facts, "bind", observed)
    reference = prices.build(quote, symbol="TEST", session="2026-10-02",
                             now=args["now"], reviews=reviews, root=tmp_path)
    assert reference["price_comparable"] is True
    assert len(calls) == 1
    assert prices.valid(reference, symbol="TEST", session="2026-10-02",
                        now=args["now"], root=tmp_path)
    assert len(calls) == 2
    (tmp_path / "test-fact.txt").write_bytes(b"TEST_ONLY source changed after build")
    assert not prices.valid(reference, symbol="TEST", session="2026-10-02",
                            now=args["now"], root=tmp_path)


def test_fresh_source_with_future_known_time_is_not_accepted(tmp_path, monkeypatch):
    args, quote, reviews = fact_inputs(tmp_path, monkeypatch)
    reviews["instrument_price_actions"]["TEST"]["known_at"] = (
        args["now"] + timedelta(seconds=1)).isoformat()
    reference = prices.build(quote, symbol="TEST", session="2026-10-02",
                             now=args["now"], reviews=reviews, root=tmp_path)
    assert reference["price_comparable"] is False
    assert reference["previous_close"] is None
    assert "BINDING_INVALID" in reference["reference_blockers"]


def test_imported_binding_without_current_interface_still_validates_original(tmp_path, monkeypatch):
    args, quote, reviews = fact_inputs(tmp_path, monkeypatch)
    quote["session_price_binding"] = facts.prepare_binding(facts.bind(quote,
        symbol="TEST", session="2026-10-02", now=args["now"], reviews=reviews, root=tmp_path))
    (tmp_path / "test-fact.txt").write_bytes(b"TEST_ONLY changed")
    reference = prices.build(quote, symbol="TEST", session="2026-10-02",
                             now=args["now"], reviews={}, root=tmp_path)
    assert reference["price_comparable"] is False
    assert reference["previous_close"] is None
