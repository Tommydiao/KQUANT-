"""P8 regressions use actual source/journal/model functions and isolated stores."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from hashlib import sha256
import json

import pytest

from test_options_opening_momentum import inputs
from kquant import options_minute_decisions as decisions
from kquant import options_opening_momentum as model
from kquant import options_opening_momentum_journal as journal
from kquant import options_one_minute as common
from kquant import options_opening_trend_store as store
from kquant.options_source_updates import merge_facts


def local_method(tmp_path, args):
    acceptance = dict(approved_by="OWNER", status="APPROVED", test_only=True,
        method_hash=common.digest(decisions.LOCAL_METHOD), approved_at=args["opening"].isoformat(),
        valid_until=(args["now"] + timedelta(hours=1)).isoformat())
    raw = json.dumps(acceptance).encode()
    (tmp_path / "TEST_ONLY_method.json").write_bytes(raw)
    return dict(status="ACCEPTED", semantics="CLOSED_SNAPSHOT_ADOPTION",
        method=deepcopy(decisions.LOCAL_METHOD), acceptance_path="TEST_ONLY_method.json",
        acceptance_sha256=sha256(raw).hexdigest())


def three_versions(args):
    end = common.timestamp(args["bars"][0]["available_at"])
    early = deepcopy(args["bars"][0])
    early.update(low=99, close=100.2, received_at=(end - timedelta(milliseconds=150)).isoformat(),
        sdk_evidence={"interface": "QuoteContext.set_on_candlestick"})
    push = deepcopy(early)
    push.update(low=99.6, close=100.3, received_at=(end + timedelta(milliseconds=50)).isoformat())
    pull = deepcopy(push)
    pull.update(low=99.8, close=100.4, received_at=(end + timedelta(milliseconds=300)).isoformat(),
        sdk_evidence=dict(interface="QuoteContext.candlesticks", adjustment="NoAdjust",
            request_started_at=(end + timedelta(milliseconds=100)).isoformat(),
            clock_evidence=dict(state="VERIFIED_BOUND", uncertainty_ms=50,
                checked_at=(end - timedelta(seconds=1)).isoformat(), source_hash="TEST_ONLY_measured_clock")))
    return early, push, pull


def test_three_versions_actual_producer_consumer_price_model_and_generation(tmp_path, monkeypatch):
    args = inputs()
    path = tmp_path / "TEST_ONLY.sqlite3"
    store.initialize(path)
    journal.initialize(path)
    monkeypatch.setattr(decisions, "ROOT", tmp_path)
    early, push, pull = three_versions(args)
    args["bars"] = [early, push, pull, *args["bars"][1:]]
    method = local_method(tmp_path, args)
    key = "opening_momentum", "2026-10-02", "TEST", 1
    job = "TEST", args["opening"].date(), args["bars"], "scope", args["reference"]
    old = journal.begin(path, key, job, args["now"])
    assert model.evaluate(**args)["reasons"] == ["SOURCE_CONFLICT"]
    resolved = decisions.resolve(path, args["bars"], symbol="TEST", session="2026-10-02",
        now=args["now"], proof=method, root=tmp_path)
    assert len(resolved) == 1
    own = resolved[0]
    assert len(own["observed_raw_ids"]) == 3
    assert set(own["eligible_version_ids"]) == {common.digest(push), common.digest(pull)}
    assert own["rejected_versions"] == {common.digest(early): "MINUTE_TIME_EVIDENCE_CONFLICT"}
    assert own["selected_version_id"] == common.digest(pull)
    assert decisions.accepted(own, [early, push, pull], symbol="TEST", start=args["opening"],
        now=args["now"], root=tmp_path) == pull
    result = model.evaluate(**args, source_decisions=resolved)
    assert result["state"] == "NUMERIC_PASS"
    assert result["deadline_at"] == "2026-10-02T13:40:00+00:00"
    fingerprint = journal.input_fingerprint(job, resolved)
    assert journal.ready(path, key, job, args["now"], fingerprint=fingerprint)
    assert not journal.finish(path, old, rows=[result])
    newest = journal.begin(path, key, job, args["now"], fingerprint=fingerprint)
    assert newest.generation == old.generation + 1
    assert journal.finish(path, newest, rows=[result])
    assert not journal.ready(path, key, job, args["now"], fingerprint=fingerprint)
    late = deepcopy(push)
    late["received_at"] = (args["now"] + timedelta(seconds=1)).isoformat()
    assert decisions.accepted(own, [early, push, pull, late], symbol="TEST", start=args["opening"],
        now=args["now"] + timedelta(seconds=2), root=tmp_path) is None


def test_illegal_version_plus_one_valid_version_needs_no_method():
    args = inputs()
    early, _, pull = three_versions(args)
    args["bars"] = [early, pull, *args["bars"][1:]]
    assert model.evaluate(**args)["state"] == "NUMERIC_PASS"


def test_bounded_commit_batch_keeps_64_independent_cas_and_deadlines(tmp_path):
    args = inputs()
    path = tmp_path / "TEST_ONLY_bounded.sqlite3"
    store.initialize(path)
    journal.initialize(path)
    entries = []
    for index in range(journal.BATCH_BOUND):
        symbol = f"TEST_ONLY_{index}"
        key = "opening_momentum", "2026-10-02", symbol, 1
        job = symbol, args["opening"].date(), [], "TEST_ONLY_scope", args["reference"]
        entries.append((key, job, args["now"], f"TEST_ONLY_input_{index}"))
    assert all(journal.ready_many(path, entries))
    leases = journal.begin_many(path, entries)
    assert len({str(lease) for lease in leases}) == journal.BATCH_BOUND
    key, job, now, _ = entries[0]
    assert journal.ready(path, key, job, now, fingerprint="TEST_ONLY_revision")
    outcomes = journal.finish_many(path, [(lease, False, []) for lease in leases])
    assert outcomes == [False] + [True] * (journal.BATCH_BOUND - 1)
    for operation in (journal.ready_many, journal.begin_many):
        with pytest.raises(ValueError, match="BOUND_EXCEEDED"):
            operation(path, entries + entries[:1])
    with pytest.raises(ValueError, match="BOUND_EXCEEDED"):
        journal.finish_many(path, [(None, False, [])] * (journal.BATCH_BOUND + 1))


@pytest.mark.parametrize("change", ["clock", "request", "expired", "wrong_method", "no_owner", "invalid_ohlc"])
def test_local_contract_cannot_legitimize_bad_inputs(tmp_path, change):
    args = inputs()
    path = tmp_path / "TEST_ONLY.sqlite3"
    journal.initialize(path)
    early, push, pull = three_versions(args)
    method = local_method(tmp_path, args)
    if change == "clock": pull["sdk_evidence"]["clock_evidence"].pop("uncertainty_ms")
    if change == "request": pull["sdk_evidence"]["request_started_at"] = pull["available_at"]
    if change == "expired": method["acceptance_sha256"] = "bad"
    if change == "wrong_method": method["method"]["combine_ohlc"] = True
    if change == "no_owner": method["status"] = "PROPOSED"
    if change == "invalid_ohlc": pull["low"] = pull["high"] + 1
    assert decisions.resolve(path, [early, push, pull], symbol="TEST", session="2026-10-02",
        now=args["now"], proof=method, root=tmp_path) == []


def test_fact_recapture_keeps_methods_and_records_real_changes(tmp_path):
    path = tmp_path / "source.json"
    original = dict(price_binding_method={"chosen": "OWNER_METHOD"},
        canonical_resolution_method={"accepted": "unchanged"}, instrument_facts={})
    path.write_text(json.dumps(original))
    fact = dict(source_sha256="old", reviewed_at="one")
    assert merge_facts(path, [(("instrument_facts", "TEST"), fact)])["changed"]
    unchanged = path.read_bytes()
    assert not merge_facts(path, [(("instrument_facts", "TEST"), {**fact, "reviewed_at": "two"})])["changed"]
    assert path.read_bytes() == unchanged
    merge_facts(path, [(("instrument_facts", "TEST"), {**fact, "source_sha256": "new"})])
    value = json.loads(path.read_bytes())
    assert value["price_binding_method"] == original["price_binding_method"]
    assert value["canonical_resolution_method"] == original["canonical_resolution_method"]
    assert value["instrument_facts"]["TEST"] == fact
    assert next(iter(value["source_update_reviews"].values()))["state"] == "REVIEW_REQUIRED"
    with pytest.raises(ValueError):
        merge_facts(path, [(("canonical_resolution_method",), None)])


def test_concurrent_fact_updates_do_not_lose_other_symbols(tmp_path):
    path = tmp_path / "source.json"
    path.write_text('{}')
    with ThreadPoolExecutor(max_workers=8) as workers:
        list(workers.map(lambda index: merge_facts(path, [(("instrument_facts", str(index)),
            {"source_sha256": str(index)})]), range(20)))
    assert len(json.loads(path.read_bytes())["instrument_facts"]) == 20


def test_failed_atomic_publish_preserves_accepted_config(tmp_path, monkeypatch):
    from kquant import options_source_updates as updates
    path = tmp_path / "source.json"
    path.write_text('{"canonical_resolution_method":{"accepted":true}}')
    before = path.read_bytes()
    monkeypatch.setattr(updates.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("TEST_ONLY_INTERRUPTED")))
    with pytest.raises(OSError):
        merge_facts(path, [(("instrument_facts", "TEST"), {"source_sha256": "new"})])
    assert path.read_bytes() == before


@pytest.mark.parametrize("title,route,expected", [
    ("Fund Preferred Securities ETF (TEST)", "etf", "US_ETF"),
    ("Company Preferred Stock (TEST)", "stocks", "US_PREFERRED"),
    ("Company Ordinary Shares (TEST)", "stocks", "US_ORDINARY_EQUITY"),
    ("Fund Exchange Traded Notes (TEST)", "stocks", "US_ETN"),
    ("Company American Depositary Shares (TEST)", "stocks", "US_ADR")])
def test_explicit_asset_types_not_stocks_path_guess(title, route, expected):
    from integrate_recaptured_assets import reviewed_page
    assert reviewed_page(f"<title>{title}</title>".encode(), symbol="TEST", expected=expected,
        url=f"https://www.nasdaq.com/market-activity/{route}/test")[0] == expected
    with pytest.raises(ValueError):
        reviewed_page(f"<title>{title}</title>".encode(), symbol="TEST", expected=expected,
            url="https://www.nasdaq.com/market-activity/stocks/other")


def test_undeclared_push_adjustment_is_not_false_basis_mismatch():
    args = inputs()
    for row in args["bars"]:
        row["sdk_evidence"] = {"interface": "QuoteContext.set_on_candlestick", "adjustment": "NOT_PROVIDED"}
    assert model.evaluate(**args)["state"] == "NUMERIC_PASS"
    args["bars"][0]["sdk_evidence"]["adjustment"] = "ForwardAdjust"
    assert model.evaluate(**args)["state"] == "INCOMPLETE"


def test_weekend_scope_is_not_falsely_active_or_stale():
    from datetime import datetime, UTC
    from kquant.options_scope_observation import apply
    payload = dict(scope_hash="declared", candidates=[{"expired": False}], snapshot={"state": "FRESH"})
    apply(payload, {"session": "2026-10-02", "scope_hash": "old"}, now=datetime(2026, 10, 4, 13, tzinfo=UTC))
    assert payload["session_state"] == "NON_TRADING_DAY"
    assert payload["snapshot"]["state"] == "FRESH" and not payload["candidates"]
    assert payload["scope_observation"]["next_session"] == "2026-10-05"
    apply(payload, {}, now=datetime(2026, 10, 5, 13, tzinfo=UTC))
    assert payload["snapshot"]["state"] == "STALE"


def test_unwindowed_actions_never_become_price_clear():
    from kquant.options_price_action_source import observe
    args = inputs()
    row = observe({"items": []}, symbol="TEST", requested_at=args["now"],
        received_at=args["now"], target_session=args["opening"].date())
    assert row["price_scale_state"] == "UNKNOWN" and row["complete"] is False
    assert "COMPANY_ACTION_WINDOW_AND_COMPLETENESS_UNCONFIRMED" in row["reasons"]


def test_policy_cache_invalidates_and_does_not_return_mutable_shared_value(tmp_path, monkeypatch):
    path = tmp_path / "policy.json"
    original = model.CONFIG.read_bytes()
    path.write_bytes(original)
    monkeypatch.setattr(model, "CONFIG", path)
    first = model.load_policy()
    first["qualified_publication_enabled"] = True
    assert model.load_policy()["qualified_publication_enabled"] is False
    value = json.loads(original)
    value["test_only_cache_probe"] = "changed"
    path.write_text(json.dumps(value))
    assert model.load_policy()["test_only_cache_probe"] == "changed"
