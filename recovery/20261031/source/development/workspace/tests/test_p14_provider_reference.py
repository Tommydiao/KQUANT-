"""TEST_ONLY P14 archives/receipts in tmp_path; no SDK or production writes."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json

import pytest

from kquant import options_clock_measurement as clock
from kquant import options_one_minute as common
from kquant import options_opening_momentum as s0
from kquant import options_provider_reference_research as research
from kquant.options_opening_trend_projection import bind_provider_reference_replay
from test_r58_p10_clock import sample


def write(root, name, value):
    raw = common.canonical(value).encode("utf-8")
    (root / name).write_bytes(raw)
    return sha256(raw).hexdigest()


def archive(root, name, value):
    body = {k: v for k, v in value.items() if k != "source_record"}
    value["source_record"] = {"source_path": name, "source_sha256": write(root, name, body), "json_pointer": ""}
    return value


def reviewed(root, name, now, **fields):
    text = "TEST_ONLY archived interface semantics"
    (root / name).write_text(text, encoding="utf-8")
    return {"source_kind": "OFFICIAL_INTERFACE_FACT", "status": "APPROVED", "reviewer": "test-reviewer",
            "review_method": "NAMED_DOCUMENT_REVIEW", "source_path": name,
            "source_sha256": sha256(text.encode()).hexdigest(), "excerpt": text,
            "reviewed_at": (now - timedelta(days=1)).isoformat(), "valid_until": (now + timedelta(days=1)).isoformat(),
            "source_url": "https://open.longbridge.com/test-only", **fields}


@pytest.fixture
def replay_inputs(tmp_path, monkeypatch):
    opening = datetime(2026, 10, 2, 13, 30, tzinfo=UTC)
    now = opening + timedelta(minutes=5, seconds=1)
    measured = opening - timedelta(seconds=10)
    monkeypatch.setattr("test_r58_p10_clock.NOW", measured)
    clock_receipt = {"status": "ACCEPTED", "accepted_by": "OWNER", "test_only": True,
        "method": clock.METHOD, "method_hash": common.digest(clock.METHOD),
        "accepted_at": (opening - timedelta(hours=1)).isoformat(), "valid_until": (opening + timedelta(days=1)).isoformat()}
    clock_proof = {"acceptance_path": "TEST_ONLY-clock.json",
        "acceptance_sha256": write(tmp_path, "TEST_ONLY-clock.json", clock_receipt)}
    bound = clock.evaluate([sample(host) for host in clock.METHOD["servers"]], proof=clock_proof, root=tmp_path, now=measured)
    assert bound["state"] == "VERIFIED_BOUND"
    bars = []
    for index in range(5):
        start = opening + timedelta(minutes=index)
        end = start + timedelta(minutes=1)
        bar = {"symbol": "TEST.US", "interval": "1m", "currency": "USD", "closed": True,
            "open_at": start.isoformat(), "available_at": end.isoformat(),
            "received_at": (end + timedelta(milliseconds=250)).isoformat(),
            "open": 100 + index, "high": 101 + index, "low": 99.9 + index, "close": 100.9 + index,
            "sdk_evidence": {"interface": "QuoteContext.candlesticks", "provider_symbol": "TEST.US",
                "adjustment": "NoAdjust", "trade_session": "Intraday", "clock_evidence": bound,
                "request_started_at": (end + timedelta(milliseconds=150)).isoformat()}}
        bars.append(archive(tmp_path, f"TEST_ONLY-minute-{index}.json", bar))
    identity = archive(tmp_path, "TEST_ONLY-identity.json", {
        "symbol": "TEST.US", "canonical_id": "TEST.US", "provider_symbol": "TEST.US", "currency": "USD",
        "exchange": "XNYS", "source": "LONGBRIDGE_SECURITY_STATIC_INFO",
        "requested_at": (opening - timedelta(hours=2)).isoformat(), "received_at": (opening - timedelta(hours=1)).isoformat()})
    quote = archive(tmp_path, "TEST_ONLY-quote.json", {
        "symbol": "TEST.US", "currency": "USD", "previous_close": 99, "provider_status": "available",
        "quote_business_session": "2026-10-02", "reference_session": "2026-10-01", "trade_session": "regular",
        "requested_at": (opening + timedelta(seconds=1)).isoformat(), "received_at": (opening + timedelta(seconds=2)).isoformat(),
        "quote_time": opening.isoformat(), "sdk_evidence": {"interface": "QuoteContext.quote", "provider_symbol": "TEST.US",
            "field": "secu_quote.prev_close", "fields": {"prev_close": 99, "native_business_day": "2026-10-02"}}})
    timeline = archive(tmp_path, "TEST_ONLY-timeline.json", {
        "symbol": "TEST.US", "provider_symbol": "TEST.US", "requested_at": opening.isoformat(),
        "received_at": (opening + timedelta(seconds=1)).isoformat(), "raw_rows": [], "parsed_rows": [], "complete": False})
    reviews = {
        "instrument_facts": {"TEST.US": reviewed(tmp_path, "TEST_ONLY-scope.txt", now,
            fact_type="INSTRUMENT_ASSET_IDENTITY", underlying="TEST.US", source_url="https://www.sec.gov/test-only")},
        "previous_close_interface": reviewed(tmp_path, "TEST_ONLY-prev.txt", now,
            fact_type="PREVIOUS_CLOSE_DEFINITION", interface="US_SECURITY_QUOTE",
            claim={"assertion": "MAIN_QUOTE_PREVIOUS_CLOSE", "field_path": "secu_quote.prev_close"}),
        "business_date_interface": reviewed(tmp_path, "TEST_ONLY-business.txt", now,
            fact_type="PREVIOUS_CLOSE_DEFINITION", interface="US_SECURITY_QUOTE",
            business_date_method="EXPLICIT_NATIVE_BUSINESS_SESSION", business_session_field="native_business_day"),
    }
    strict = {"contract_version": "PRICE_REFERENCE_V2", "symbol": "TEST.US", "canonical_id": "TEST.US",
        "session": "2026-10-02", "reference_session": "2026-10-01", "currency": "USD",
        "price_comparable": False, "previous_close": None, "reference_blockers": ["STRICT_ACTION_COMPLETENESS_MISSING"]}
    args = {"symbol": "TEST.US", "right": "CALL", "bars": bars, "history": {}, "reference": strict,
        "opening": opening, "closing": opening + timedelta(hours=6, minutes=30), "now": now, "scope_hash": "TEST_ONLY-scope"}
    text = research.proposal()["acceptance_text"]
    (tmp_path / "TEST_ONLY-owner-reply.txt").write_text(text, encoding="utf-8")
    receipt = {"schema": research.METHOD_ID + "_OWNER_RECEIPT", "status": "ACCEPTED", "accepted_by": "OWNER",
        "method": research.proposal()["method"], "method_hash": research.RULE_HASH, "scope": "READ_ONLY_RESEARCH_CANDIDATE",
        "source_root": str(tmp_path.resolve()), "accepted_at": (opening - timedelta(hours=1)).isoformat(),
        "valid_until": (opening + timedelta(days=1)).isoformat(), "test_only": True,
        "user_reply_path": "TEST_ONLY-owner-reply.txt", "user_reply_sha256": sha256(text.encode()).hexdigest()}
    proof = {"acceptance_path": "TEST_ONLY-research-receipt.json",
        "acceptance_sha256": write(tmp_path, "TEST_ONLY-research-receipt.json", receipt)}
    return {"arguments": args, "quote": quote, "identity": identity, "timeline": timeline,
        "reviews": reviews, "root": tmp_path, "checked_at": now, "method_proof": proof}


def compute(inputs):
    return research.evaluate_replay(**inputs, enabled=True)


def test_exact_proposal_default_disabled_and_printable():
    proposal = research.proposal()
    assert proposal["status"] == "PROPOSAL_ONLY" and proposal["enabled"] is False
    assert proposal["method"]["default_enabled"] is False
    assert proposal["rule_hash"] == common.digest(proposal["method"])
    assert proposal["rule_hash"] in proposal["acceptance_text"]
    proposal["method"]["default_enabled"] = True
    assert research.proposal()["method"]["default_enabled"] is False


def test_disable_does_not_enter_research_and_preserves_original(replay_inputs, monkeypatch):
    original = s0.evaluate(**replay_inputs["arguments"])
    monkeypatch.setattr(research, "_reference", lambda *a, **k: pytest.fail("disabled entered research"))
    result = research.evaluate_replay(**replay_inputs)
    assert result["research_computation_state"] == "DISABLED"
    assert result["accepted_method"] is None
    assert result["original_strict_result"] == original
    replay_inputs["method_proof"] = None
    result = compute(replay_inputs)
    assert result["research_computation_state"] == "DISABLED"
    assert result["accepted_method"] is None


@pytest.mark.parametrize("defect", ["hash", "method", "root", "scope", "owner", "future", "expired", "reply", "escape"])
def test_receipt_independent_exact_root_time_and_reply(replay_inputs, defect):
    root, proof = replay_inputs["root"], replay_inputs["method_proof"]
    path = root / proof["acceptance_path"]
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if defect == "hash": receipt["method_hash"] = "0" * 64
    if defect == "method": receipt["method"]["default_enabled"] = True
    if defect == "root": receipt["source_root"] = str(root.parent)
    if defect == "scope": receipt["scope"] = "SHADOW_RUNTIME"
    if defect == "owner": receipt["accepted_by"] = "AUTOMATED"
    if defect == "future": receipt["accepted_at"] = (replay_inputs["checked_at"] + timedelta(seconds=1)).isoformat()
    if defect == "expired": receipt["valid_until"] = replay_inputs["checked_at"].isoformat()
    if defect == "reply":
        (root / receipt["user_reply_path"]).write_text("not accepted", encoding="utf-8")
        receipt["user_reply_sha256"] = sha256(b"not accepted").hexdigest()
    if defect == "escape": receipt["user_reply_path"] = "../outside-root.txt"
    proof["acceptance_sha256"] = write(root, path.name, receipt)
    result = compute(replay_inputs)
    assert result["research_computation_state"] == "DISABLED"
    assert result["accepted_method"] is None


@pytest.mark.parametrize("right,state", [("CALL", "COMPLETE"), ("PUT", "NO_TRIGGER")])
def test_same_formula_separate_assumption_no_strict_verified(replay_inputs, right, state):
    replay_inputs["arguments"]["right"] = right
    before = deepcopy(replay_inputs)
    result = compute(replay_inputs)
    assert replay_inputs == before
    assert result["research_computation_state"] == state, result["reasons"]
    assert result["strict_s0_state"] == "INCOMPLETE"
    assert result["original_strict_result"] == s0.evaluate(**replay_inputs["arguments"])
    assert result["original_strict_result"]["factor_evidence"]["state"] == "PARTIAL_PRICE_COMPONENTS"
    assert result["evidence_mode"] == "REPLAY_ONLY" and result["live_observed"] is False
    assert not result["strict_reference_verified"] and not result["qualified_signal"]
    assert "qualified_claims" not in result and "state" not in result
    assert "evaluation_id" not in result["formula_result"]
    assert result["formula_result"]["input_checks"]["reference"]["state"] == "PROVIDER_NATIVE_ASSUMPTION"
    ref = result["formula_result"]["reference_evidence"]
    assert ref["price_comparable"] is False and "contract_version" not in ref
    assert result["formula_result"]["factor_evidence"]["auxiliary"]["state"] == "UNVERIFIED"
    assert result["known_events"] == [] and result["gaps"]
    if right == "CALL":
        assert result["formula_result"]["deadline_at"] == "2026-10-02T13:40:00+00:00"
        assert result["formula_result"]["factor_evidence"]["momentum"] == pytest.approx(4.9 / 5.1)


@pytest.mark.parametrize("defect", ["symbol", "currency", "identity", "calendar", "premarket", "daily", "value", "boolean",
    "native_value", "future", "request_order", "business_missing", "wrong_business", "wrong_reference", "time_inference", "archive", "source"])
def test_native_identity_business_date_and_source_negatives(replay_inputs, defect):
    quote, identity, root = replay_inputs["quote"], replay_inputs["identity"], replay_inputs["root"]
    if defect == "symbol": quote["symbol"] = "OTHER.US"
    if defect == "currency": quote["currency"] = "HKD"
    if defect == "identity": identity["canonical_id"] = "OTHER.US"
    if defect == "calendar": identity["exchange"] = "UNVERIFIED"
    if defect == "premarket": quote["trade_session"] = "pre_market"
    if defect == "daily": quote["sdk_evidence"]["interface"] = "QuoteContext.history_candlesticks_by_date"
    if defect == "value": quote["previous_close"] = 0
    if defect == "boolean": quote["previous_close"] = True
    if defect == "native_value": quote["sdk_evidence"]["fields"]["prev_close"] = 98
    if defect == "future": quote["received_at"] = (replay_inputs["arguments"]["now"] + timedelta(seconds=1)).isoformat()
    if defect == "request_order": quote["requested_at"] = replay_inputs["arguments"]["now"].isoformat()
    if defect == "business_missing": replay_inputs["reviews"].pop("business_date_interface")
    if defect == "wrong_business": quote["sdk_evidence"]["fields"]["native_business_day"] = "2026-10-01"
    if defect == "wrong_reference": quote["reference_session"] = "2026-09-30"
    if defect == "time_inference":
        replay_inputs["reviews"]["business_date_interface"]["business_session_field"] = "quote_time"
        quote["sdk_evidence"]["fields"]["quote_time"] = "2026-10-02"
    if defect == "source": (root / "TEST_ONLY-prev.txt").write_text("changed", encoding="utf-8")
    archive(root, "TEST_ONLY-identity.json", identity)
    if defect != "archive": archive(root, "TEST_ONLY-quote.json", quote)
    else: quote["previous_close"] = 120
    result = compute(replay_inputs)
    assert result["research_computation_state"] == "INCOMPLETE", result
    assert "formula_result" not in result and result["strict_s0_state"] == "INCOMPLETE"


@pytest.mark.parametrize("defect", ["currency", "symbol", "adjustment", "session", "missing", "clock", "boundary", "conflict", "clock_hash"])
def test_minute_time_clock_and_canonical_fail_closed(replay_inputs, defect):
    row = replay_inputs["arguments"]["bars"][0]
    if defect == "currency": row["currency"] = "HKD"
    if defect == "symbol": row["symbol"] = "OTHER.US"
    if defect == "adjustment": row["sdk_evidence"]["adjustment"] = "ForwardAdjust"
    if defect == "session": row["sdk_evidence"]["trade_session"] = "PreMarket"
    if defect == "missing": replay_inputs["arguments"]["bars"].pop()
    if defect == "clock": row["sdk_evidence"]["clock_evidence"]["precision_verified"] = False
    if defect == "clock_hash": row["sdk_evidence"]["clock_evidence"]["source_hash"] = "0" * 64
    if defect == "boundary": row["sdk_evidence"]["request_started_at"] = row["available_at"]
    archive(replay_inputs["root"], "TEST_ONLY-minute-0.json", row)
    if defect == "conflict":
        other = deepcopy(row)
        other["open"] += .01
        other["sdk_evidence"]["interface"] = "QuoteContext.set_on_candlestick"
        replay_inputs["arguments"]["bars"].append(archive(replay_inputs["root"], "TEST_ONLY-conflict.json", other))
    result = compute(replay_inputs)
    assert result["research_computation_state"] == "INCOMPLETE"
    assert "formula_result" not in result


@pytest.mark.parametrize("defect", ["known_scale", "unknown", "missing_parsed", "filtered", "duplicate_locator"])
def test_observed_actions_cannot_be_filtered_or_declared_clear(replay_inputs, defect):
    timeline = replay_inputs["timeline"]
    timeline["raw_rows"] = [{"id": "same", "type": "Split", "date": "2026-10-02"},
                            {"id": "same", "type": "Split", "date": "2026-10-03"}]
    timeline["parsed_rows"] = [{"source_index": i, "source_locator": f"/raw_rows/{i}", "raw_id": "same",
        "query_symbol": "TEST.US", "native_category": "Split", "native_date": row["date"],
        "parse_status": "PARSED", "relevance_to_price_scale": "PRICE_SCALE"} for i, row in enumerate(timeline["raw_rows"])]
    if defect == "unknown": timeline["parsed_rows"][0]["relevance_to_price_scale"] = "UNKNOWN"
    if defect == "missing_parsed": timeline["parsed_rows"] = []
    if defect == "filtered": timeline["parsed_rows"].pop()
    if defect == "duplicate_locator": timeline["parsed_rows"][1]["source_index"] = 0
    archive(replay_inputs["root"], "TEST_ONLY-timeline.json", timeline)
    result = compute(replay_inputs)
    assert result["reasons"] == ["PRICE_SCALE_REVIEW"]
    assert result["known_events"] == timeline["parsed_rows"]
    assert result["gaps"] and not result["strict_reference_verified"]


def test_mapped_irrelevant_rows_still_disclose_incomplete_history(replay_inputs):
    timeline = replay_inputs["timeline"]
    timeline["raw_rows"] = [{"id": "report", "type": "FinancialReport", "date": "2026-10-01"}]
    timeline["parsed_rows"] = [{"source_index": 0, "source_locator": "/raw_rows/0", "raw_id": "report",
        "query_symbol": "TEST.US", "native_category": "FinancialReport", "native_date": "2026-10-01",
        "parse_status": "PARSED", "relevance_to_price_scale": "NOT_PRICE_SCALE"}]
    mapping = reviewed(replay_inputs["root"], "TEST_ONLY-action.txt", replay_inputs["arguments"]["now"],
        action_classification_rules={"FinancialReport": "NOT_PRICE_SCALE"})
    mapping["source_kind"] = "OFFICIAL_DOCUMENT"
    replay_inputs["reviews"]["action_mapping"] = mapping
    archive(replay_inputs["root"], "TEST_ONLY-timeline.json", timeline)
    result = compute(replay_inputs)
    assert result["research_computation_state"] == "COMPLETE", result["reasons"]
    assert result["gaps"] and result["known_events"]
    assert timeline["complete"] is False


def test_deadline_policy_and_projection_are_disjoint(replay_inputs):
    original = deepcopy(replay_inputs["arguments"]["reference"])
    result = compute(replay_inputs)
    view = bind_provider_reference_replay(result["original_strict_result"], result)
    assert view["strict_result"]["state"] == "INCOMPLETE"
    assert view["provider_reference_research"]["research_computation_state"] == "COMPLETE"
    assert replay_inputs["arguments"]["reference"] == original
    changed = deepcopy(result)
    changed["strict_reference_verified"] = True
    changed["snapshot_id"] = common.digest({k: v for k, v in changed.items() if k != "snapshot_id"})
    assert research.project_replay(view["strict_result"], changed)["research_computation_state"] == "UNAVAILABLE"
    changed = deepcopy(view["strict_result"])
    changed["state"] = "NUMERIC_PASS"
    assert research.project_replay(changed, result)["research_computation_state"] == "UNAVAILABLE"
    replay_inputs["arguments"]["checkpoint"] = replay_inputs["arguments"]["opening"] + timedelta(minutes=5)
    replay_inputs["arguments"]["now"] = replay_inputs["arguments"]["opening"] + timedelta(minutes=10)
    replay_inputs["checked_at"] = replay_inputs["arguments"]["now"]
    expired = compute(replay_inputs)
    assert expired["formula_state"] == "EXPIRED"
    assert expired["formula_result"]["deadline_at"] == "2026-10-02T13:40:00+00:00"
    assert expired["research_computation_state"] == "INCOMPLETE"
    policy = s0.load_policy()
    policy["momentum_min"] = 0
    replay_inputs["arguments"]["policy"] = policy
    assert compute(replay_inputs)["reasons"] == ["ORIGINAL_S0_POLICY_CHANGED"]
