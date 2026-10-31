from copy import deepcopy
from datetime import timedelta
import json
from hashlib import sha256
import sqlite3

import pytest

from test_options_opening_momentum import inputs
from kquant import options_one_minute as common
from kquant import options_price_reference as prices
from kquant import options_opening_momentum as model
from kquant import options_opening_momentum_journal as journal
from kquant import options_minute_decisions as decisions
from kquant import options_opening_trend_summary as summary


def proof(tmp_path, now, **fields):
    raw = b"TEST_ONLY isolated source fact, not a production proof"
    (tmp_path / "test-fact.txt").write_bytes(raw)
    return dict(status="APPROVED", reviewer="test-only-reviewer", reviewed_at=now.isoformat(),
        valid_until=(now + timedelta(hours=1)).isoformat(), source_path="test-fact.txt",
        source_url=fields.pop("source_url", "https://open.longbridge.com/docs/quote/pull/quote"), source_sha256=sha256(raw).hexdigest(),
        excerpt="TEST_ONLY isolated source fact", **fields)


def reference(tmp_path, monkeypatch):
    args = inputs()
    now = args["now"]
    monkeypatch.setattr(prices, "ROOT", tmp_path)
    currency = dict(symbol="TEST", currency="USD", source="LONGBRIDGE_SECURITY_STATIC_INFO")
    currency["source_hash"] = common.digest(currency)
    quote = dict(symbol="TEST", provider_status="available", previous_close=100,
        requested_at=args["opening"].isoformat(), received_at=now.isoformat(),
        quote_time=args["opening"].isoformat(), currency="USD", currency_evidence=currency)
    reviews = dict(previous_close_interface=proof(tmp_path, now, interface="US_SECURITY_QUOTE", field="prev_close",
        meaning="PREVIOUS_REGULAR_SESSION_CLOSE", business_session_field="quote_business_session"),
        price_comparability=proof(tmp_path, now, interface="US_SECURITY_QUOTE_AND_CANDLESTICK", price_basis="NoAdjust",
            symbol="TEST", session="2026-10-02", corporate_action_comparability="COMPARABLE"))
    return args, quote, reviews


def test_different_last_minute_close_does_not_veto_price_or_require_history(tmp_path, monkeypatch):
    args, quote, reviews = reference(tmp_path, monkeypatch)
    args["reference"] = prices.build(quote, symbol="TEST", session="2026-10-02", now=args["now"],
        reviews=reviews, root=tmp_path, prior_close_bar={"close": 99.99})
    assert args["reference"]["previous_close"] == 100
    assert args["reference"]["previous_last_minute_close"] == 99.99
    assert model.evaluate(**args)["state"] == "NUMERIC_PASS"
    assert model.evaluate(**args)["factor_evidence"]["auxiliary"]["state"] == "UNVERIFIED"


@pytest.mark.parametrize("change", ["date", "currency", "adjustment", "future", "source"])
def test_matching_prices_do_not_prove_reference_identity(tmp_path, monkeypatch, change):
    args, quote, reviews = reference(tmp_path, monkeypatch)
    if change == "date": quote["reference_session"] = "2026-09-29"
    if change == "currency": quote["currency"] = "HKD"
    if change == "adjustment": reviews["price_comparability"]["price_basis"] = "ForwardAdjust"
    if change == "future": quote["quote_time"] = (args["now"] + timedelta(seconds=15)).isoformat()
    if change == "source": reviews["previous_close_interface"]["source_sha256"] = "changed"
    args["reference"] = prices.build(quote, symbol="TEST", session="2026-10-02", now=args["now"], reviews=reviews, root=tmp_path)
    assert model.evaluate(**args)["state"] == "INCOMPLETE"


def test_trade_timestamp_is_not_reference_business_date(tmp_path, monkeypatch):
    args, quote, reviews = reference(tmp_path, monkeypatch)
    quote["quote_time"] = "2026-10-01T19:59:00+00:00"
    quote["quote_business_session"] = "2026-10-02"
    value = prices.build(quote, symbol="TEST", session="2026-10-02", now=args["now"], reviews=reviews, root=tmp_path)
    assert prices.valid(value, symbol="TEST", session="2026-10-02", now=args["now"])
    del quote["quote_business_session"]
    assert prices.build(quote, symbol="TEST", session="2026-10-02", now=args["now"], reviews=reviews, root=tmp_path)["reference_blockers"] == ["REFERENCE_BUSINESS_DATE_AMBIGUOUS"]


def test_comparability_map_is_per_symbol_and_session_not_a_single_watchlist_proof(tmp_path, monkeypatch):
    args, quote, reviews = reference(tmp_path, monkeypatch)
    second = {**reviews["price_comparability"], "symbol": "SECOND"}
    reviews["price_comparability_by_symbol_session"] = {
        "2026-10-02": {"TEST": reviews["price_comparability"], "SECOND": second}}
    for symbol in ("TEST", "SECOND"):
        native = {**quote, "symbol": symbol}
        currency = {**quote["currency_evidence"], "symbol": symbol}
        currency.pop("source_hash")
        native["currency_evidence"] = {**currency, "source_hash": common.digest(currency)}
        result = prices.build(native, symbol=symbol, session="2026-10-02", now=args["now"], reviews=reviews, root=tmp_path)
        assert prices.valid(result, symbol=symbol, session="2026-10-02", now=args["now"])
    # An explicit map is authoritative; missing entries cannot borrow the legacy proof.
    reviews["price_comparability_by_symbol_session"] = {"2026-10-01": {"TEST": reviews["price_comparability"]}}
    value = prices.build(quote, symbol="TEST", session="2026-10-02", now=args["now"], reviews=reviews, root=tmp_path)
    assert "ADJUSTMENT_REVIEW" in value["reference_blockers"]


def test_ready_survives_crash_before_begin_and_wait_input_preserves_checkpoint(tmp_path):
    args = inputs()
    path = tmp_path / "journal.db"
    journal.initialize(path)
    key = ("opening_momentum", "2026-10-02", "TEST", 1)
    job = ("TEST", args["opening"].date(), [], "scope", args["reference"])
    assert journal.ready(path, key, job, args["now"])
    assert journal.restore(path, args["now"])[key] == job
    identity = journal.begin(path, key, job, args["now"])
    journal.finish(path, identity, waiting=True)
    at_939 = args["opening"] + timedelta(minutes=9)
    assert list(journal.restore(path, at_939)) == [key]
    assert not journal.ready(path, key, job, args["opening"] + timedelta(minutes=10))
    with sqlite3.connect(path) as db:
        state, deadline = db.execute("SELECT state,deadline_at FROM two_hour_jobs").fetchone()
    assert state == "EXPIRED" and deadline == "2026-10-02T13:40:00+00:00"


def test_reviewed_canonical_resolution_is_asof_and_uses_one_whole_version(tmp_path, monkeypatch):
    args = inputs()
    first = args["bars"][0]
    first["sdk_evidence"] = {"interface": "QuoteContext.set_on_candlestick"}
    corrected = {**first, "open": 100.2, "sdk_evidence": {"interface": "QuoteContext.candlesticks"},
        "received_at": args["now"].isoformat()}
    args["bars"].append(corrected)
    assert model.evaluate(**args)["state"] == "INCOMPLETE"
    path = tmp_path / "journal.db"
    journal.initialize(path)
    monkeypatch.setattr(decisions, "ROOT", tmp_path)
    known = args["now"]
    value = decisions.append(path, dict(state="RESOLVED_VALID", symbol="TEST", session="2026-10-02",
        open_at=first["open_at"], known_at=known.isoformat(), resolved_at=known.isoformat(), valid_from=known.isoformat(),
        selected_version_id=common.digest(corrected), source_version_ids=[common.digest(first), common.digest(corrected)],
        source_semantics=proof(tmp_path, known, interface="US_EQUITY_CANDLESTICK_1M", semantics="FINAL_CORRECTION")))
    args["source_decisions"] = [value]
    assert model.evaluate(**args)["state"] == "NUMERIC_PASS"
    future = {**value, "known_at": (known + timedelta(minutes=1)).isoformat(),
              "valid_from": (known + timedelta(minutes=1)).isoformat()}
    args["source_decisions"] = [value, future]
    assert model.evaluate(**args)["state"] == "NUMERIC_PASS"
    args["source_decisions"] = [{**value, "valid_from": (known + timedelta(seconds=1)).isoformat()}]
    assert model.evaluate(**args)["state"] == "INCOMPLETE"
    args["source_decisions"] = [value]
    args["bars"].append({**corrected, "open": 100.3, "received_at": (known + timedelta(seconds=1)).isoformat()})
    args["now"] += timedelta(seconds=2)
    assert model.evaluate(**args)["state"] == "INCOMPLETE"


def test_final_compact_removes_all_1110_details_and_is_idempotent():
    raw = dict(evaluations=[], candidates=[], checkpoint_coverage={"checkpoints": [
        {"bar_end": str(i), "registered_directions": 222, "items": [dict(symbol=str(n), reasons=["MISSING"]) for n in range(222)]}
        for i in range(5)]})
    original = deepcopy(raw)
    value = summary.compact_status(raw)
    assert len(json.dumps(value).encode()) < 32768
    assert all("items" not in row and row["reason_counts"] == {"MISSING": 222} for row in value["checkpoint_coverage"]["checkpoints"])
    assert summary.compact_status(value) == value
    assert raw == original


def test_s1_changes_only_previous_close_direction_gate_and_cannot_route(tmp_path, monkeypatch):
    from kquant.options_opening_momentum_s1 import POLICY_ID
    assert POLICY_ID == "STRAT-SESSION-DIRECTION-5M-CHALLENGER-V1"
    from kquant import options_opening_momentum_s1 as s1
    protocol = tmp_path / 'TEST_ONLY-protocol.md'
    protocol.write_text('TEST_ONLY mechanism fixture; not a preregistration or approval.', encoding='utf-8')
    monkeypatch.setattr(s1, 'PROTOCOL', protocol)
    args = inputs()
    args["reference"]["previous_close"] = 110
    assert model.evaluate(**args)["state"] == "NO_TRIGGER"
    result = s1.evaluate(**args)
    assert result["state"] == "NUMERIC_PASS" and result["production_routing"] is False
    with pytest.raises(ValueError, match="UNKNOWN_STRATEGY_VERSION"):
        model.policy_for(result)
    with pytest.raises(ValueError, match="S1_PARAMETERS_FROZEN"):
        s1.evaluate(**args, policy={})


def test_missing_s1_protocol_is_not_synthesized_or_routed(tmp_path, monkeypatch):
    from kquant import options_opening_momentum_s1 as s1
    protocol = tmp_path / 'missing-preregistration.md'
    monkeypatch.setattr(s1, 'PROTOCOL', protocol)
    with pytest.raises(FileNotFoundError):
        s1.evaluate(**inputs())
    assert not protocol.exists()


def test_reference_callback_preserves_original_slot_instead_of_current_time():
    from collections import OrderedDict
    from threading import Condition
    from kquant.options_opening_trend_runtime import TrendLane
    args = inputs()
    lane = TrendLane.__new__(TrendLane)
    key = ("opening_momentum", "2026-10-02", "TEST", 1)
    job = ("TEST", args["opening"].date(), [], "scope", args["reference"])
    lane.waiting, lane.incoming, lane.pending = {key: job}, OrderedDict(), OrderedDict()
    lane.lock, lane.stopped = Condition(), False
    lane.latest_inputs = {("TEST", job[1]): job}
    lane.clock = lambda: args["opening"] + timedelta(minutes=9)
    lane.reference_ready("TEST", job[1], {"changed": True})
    assert list(lane.incoming) == [key]
    assert lane.incoming[key][-1] == {"changed": True}


def test_predeployment_checkpoint_is_not_backdated_system_gap():
    from kquant.options_opening_trend_coverage import reconcile
    args = inputs()
    value = reconcile([{"symbol": "TEST", "identity_status": "verified"}], [],
        now=args["opening"] + timedelta(hours=1), scope_hash="scope", policy=model.load_policy(),
        observer_started_at=(args["opening"] + timedelta(minutes=12)).isoformat())
    assert value["checkpoints"][0]["pre_deployment_directions"] == 2
    assert value["checkpoints"][0]["missing_directions"] == 0
    assert value["checkpoints"][2]["missing_directions"] == 2
    assert value["state"] == "SYSTEM_GAPS"
