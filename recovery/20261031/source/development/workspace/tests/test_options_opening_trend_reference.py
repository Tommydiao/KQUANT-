from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json

from kquant.options_opening_trend_reference import build, source_review, contract_sources
from kquant import options_one_minute as common

NOW = datetime(2026, 9, 29, 13, 50, tzinfo=UTC)


def test_clock_conflict_has_its_own_evidence_and_does_not_retime_quote():
    quote = dict(symbol="TEST", provider_status="available", previous_close=100,
                 quote_time=(NOW + timedelta(seconds=15)).isoformat(), received_at=NOW.isoformat())
    original = deepcopy(quote)
    result = build(quote, symbol="TEST", session="2026-09-29", now=NOW)
    assert "REFERENCE_TIME_CONFLICT" in result["reference_blockers"]
    assert result["time_evidence"]["provider_ahead_seconds"] == 15
    assert result["previous_close"] is None
    assert quote == original
    later = build(quote, symbol="TEST", session="2026-09-29", now=NOW + timedelta(seconds=30))
    assert "REFERENCE_TIME_CONFLICT" in later["reference_blockers"]


def test_quote_does_not_prove_units_or_comparability():
    quote = dict(symbol="TEST", provider_status="available", previous_close=100,
                 quote_time=NOW.isoformat(), received_at=NOW.isoformat())
    result = build(quote, symbol="TEST", session="2026-09-29", now=NOW)
    assert result["previous_close"] == 100
    assert result["volume_unit"] == "UNKNOWN"
    assert not result["price_comparable"]


def test_previous_session_response_cannot_supply_today_reference():
    quote = dict(symbol="TEST", provider_status="available", previous_close=100,
                 quote_time="2026-09-28T19:59:00+00:00", received_at=NOW.isoformat())
    assert build(quote, symbol="TEST", session="2026-09-29", now=NOW)["previous_close"] is None


def test_review_requires_source_content_not_verified_string(tmp_path):
    raw = b"TEST_ONLY official unit statement"
    path = tmp_path / "source.txt"
    path.write_bytes(raw)
    row = dict(status="APPROVED", reviewer="test-reviewer", reviewed_at="2026-09-29T13:00:00+00:00",
               valid_until="2026-09-29T20:00:00+00:00", source_url="https://open.longbridge.com/docs/quote/pull/candlestick",
               source_path="source.txt", source_sha256=sha256(raw).hexdigest(), excerpt="official unit statement")
    assert source_review(row, root=tmp_path, now=NOW) == row
    path.write_bytes(b"changed source")
    assert source_review(row, root=tmp_path, now=NOW) is None


def test_unapproved_statement_does_not_pass(tmp_path):
    assert source_review({"status": "VERIFIED"}, root=tmp_path, now=NOW) is None
    assert source_review([], root=tmp_path, now=NOW) is None


def reply_fixture(tmp_path):
    raw = b"TEST_ONLY original provider reply: volume is shares"
    (tmp_path / "reply.txt").write_bytes(raw)
    row = dict(status="APPROVED", reviewer="test-reviewer", reviewed_at=NOW.isoformat(),
               valid_until=(NOW+timedelta(days=1)).isoformat(), source_kind="FORMAL_PROVIDER_REPLY",
               source_path="reply.txt", source_sha256=sha256(raw).hexdigest(), excerpt="volume is shares",
               interface="US_EQUITY_CANDLESTICK_1M", authenticity_review_path="review.json")
    review = dict(status="ACCEPTED", provider="LONGBRIDGE", channel="SUPPORT_TICKET",
                  reference_id="TEST_ONLY-123", issuer_origin="TEST_ONLY provider portal",
                  method="ORIGINAL_PROVIDER_CHANNEL_MANUALLY_VERIFIED", reviewer=row["reviewer"],
                  issued_at=(NOW-timedelta(hours=1)).isoformat(), reviewed_at=row["reviewed_at"],
                  source_sha256=row["source_sha256"], applicable_interfaces=[row["interface"]])
    data = json.dumps(review).encode()
    (tmp_path / "review.json").write_bytes(data)
    row["authenticity_review_sha256"] = sha256(data).hexdigest()
    return row, review


def test_formal_reply_needs_original_and_separate_review_not_a_domain_flag(tmp_path):
    row, _ = reply_fixture(tmp_path)
    assert source_review(row, root=tmp_path, now=NOW) == row
    (tmp_path / "reply.txt").write_bytes(b"modified but not re-reviewed")
    assert source_review(row, root=tmp_path, now=NOW) is None


def test_formal_reply_missing_changed_or_malformed_review_is_rejected(tmp_path):
    row, _ = reply_fixture(tmp_path)
    (tmp_path / "review.json").write_bytes(b"changed")
    assert source_review(row, root=tmp_path, now=NOW) is None
    (tmp_path / "review.json").unlink()
    assert source_review(row, root=tmp_path, now=NOW) is None
    (tmp_path / "review.json").write_bytes(b"[]")
    row["authenticity_review_sha256"] = sha256(b"[]").hexdigest()
    assert source_review(row, root=tmp_path, now=NOW) is None


def test_formal_reply_requires_interface_time_and_named_manual_review(tmp_path):
    row, review = reply_fixture(tmp_path)
    for key, value in [("applicable_interfaces", ["US_OPTION_DEPTH"]),
                       ("issued_at", (NOW+timedelta(seconds=1)).isoformat()),
                       ("method", "AUTOMATIC"), ("reviewer", "other"), ("status", "VERIFIED")]:
        changed = {**review, key: value}
        data = json.dumps(changed).encode()
        (tmp_path / "review.json").write_bytes(data)
        row["authenticity_review_sha256"] = sha256(data).hexdigest()
        assert source_review(row, root=tmp_path, now=NOW) is None


def test_unknown_source_kind_and_local_or_credential_urls_never_widen_document_access(tmp_path):
    row, _ = reply_fixture(tmp_path)
    for kind, url in [("VERIFIED_STRING", "https://open.longbridge.com"),
                      ("OFFICIAL_DOCUMENT", "https://example.com"),
                      ("OFFICIAL_DOCUMENT", "https://secret@open.longbridge.com")]:
        assert source_review({**row, "source_kind": kind, "source_url": url}, root=tmp_path, now=NOW) is None


def contract_fixture(tmp_path):
    raw = b"TEST_ONLY depth and deliverable proof"
    (tmp_path / "source.txt").write_bytes(raw)
    proof = dict(status="APPROVED", reviewer="test-reviewer", reviewed_at=(NOW-timedelta(minutes=1)).isoformat(),
                 valid_until=(NOW+timedelta(minutes=10)).isoformat(),
                 source_url="https://open.longbridge.com/docs/quote/pull/depth", source_path="source.txt",
                 source_sha256=sha256(raw).hexdigest(), excerpt="depth and deliverable proof")
    units = {**proof, "interface": "US_OPTION_DEPTH", "raw_units_per_contract": 100}
    deliverable = {**proof, "contract_symbol": "TESTC", "underlying": "TEST",
                   "deliverable_type": "STANDARD", "adjusted": False,
                   "valid_until": (NOW+timedelta(seconds=2)).isoformat()}
    multiplier = {**proof, "interface": "US_OPTION_QUOTE", "contract_symbol": "TESTC", "underlying": "TEST",
                  "multiplier_field": "contract_multiplier", "multiplier": 100}
    row = dict(contract_id="TESTC", underlying="TEST", deliverable="STANDARD", adjusted=False,
               quantity_evidence=deepcopy(units), deliverable_evidence=deepcopy(deliverable),
               multiplier_evidence=deepcopy(multiplier), multiplier_status="VERIFIED_NATIVE_FIELD", multiplier=100, raw_multiplier=100,
               size_unit_status="VERIFIED_CONTRACTS", raw_bid_size=100, raw_ask_size=200, bid_size=1, ask_size=2)
    return row, {"depth_units": units, "deliverables": {"TESTC": deliverable}, "quote_multipliers": {"TESTC": multiplier}}


def test_contract_sources_preserve_bound_proofs_and_exact_expiry(tmp_path):
    row, reviews = contract_fixture(tmp_path)
    original = deepcopy(row)
    result = contract_sources(row, reviews, root=tmp_path, now=NOW)
    assert result["status"] == "PASS"
    assert result["valid_until"] == (NOW+timedelta(seconds=2)).isoformat()
    assert row == original
    expired = contract_sources(row, reviews, root=tmp_path, now=NOW+timedelta(seconds=2))
    assert expired["status"] == "BLOCKED"
    assert expired["reasons"] == ["CONTRACT_DELIVERABLE_SOURCE_UNAVAILABLE"]


def test_source_refresh_cannot_replace_first_selected_binding(tmp_path):
    row, reviews = contract_fixture(tmp_path)
    bound = contract_sources(row, reviews, root=tmp_path, now=NOW)["source_binding"]
    reviews["depth_units"]["raw_units_per_contract"] = 10
    row.update(quantity_evidence=deepcopy(reviews["depth_units"]), bid_size=10, ask_size=20)
    result = contract_sources(row, reviews, root=tmp_path, now=NOW, binding=bound)
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["CONTRACT_DEPTH_UNITS_SOURCE_CHANGED"]


def test_source_content_change_and_revocation_block_without_sdk(tmp_path):
    row, reviews = contract_fixture(tmp_path)
    (tmp_path / "source.txt").write_bytes(b"changed evidence")
    result = contract_sources(row, reviews, root=tmp_path, now=NOW)
    assert result["status"] == "BLOCKED" and len(result["reasons"]) == 3
    reviews["depth_units"]["status"] = "REVOKED"
    result = contract_sources(row, reviews, root=tmp_path, now=NOW)
    assert "CONTRACT_DEPTH_UNITS_SOURCE_CHANGED" in result["reasons"]


def test_depth_conversion_and_deliverable_identity_are_rechecked(tmp_path):
    row, reviews = contract_fixture(tmp_path)
    row.update(bid_size=100, underlying="OTHER")
    result = contract_sources(row, reviews, root=tmp_path, now=NOW)
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["CONTRACT_DEPTH_UNIT_CONVERSION_UNVERIFIED", "CONTRACT_DELIVERABLE_IDENTITY_UNVERIFIED", "CONTRACT_QUOTE_MULTIPLIER_IDENTITY_UNVERIFIED"]
    assert result["valid_until"] is None


def test_legacy_selected_row_cannot_adopt_new_binding(tmp_path):
    row, reviews = contract_fixture(tmp_path)
    result = contract_sources(row, reviews, root=tmp_path, now=NOW, binding={})
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["CONTRACT_DEPTH_UNITS_SOURCE_MISSING", "CONTRACT_DELIVERABLE_SOURCE_MISSING", "CONTRACT_QUOTE_MULTIPLIER_SOURCE_MISSING"]


def test_multiplier_is_independent_and_cannot_borrow_contract_size(tmp_path):
    row, reviews = contract_fixture(tmp_path)
    reviews["quote_multipliers"].clear()
    assert "CONTRACT_QUOTE_MULTIPLIER_SOURCE_CHANGED" in contract_sources(row, reviews, root=tmp_path, now=NOW)["reasons"]
    row, reviews = contract_fixture(tmp_path)
    for change in ({"raw_multiplier": None, "contract_size": 100}, {"raw_multiplier": 10},
                   {"multiplier_status": "UNVERIFIED"}, {"multiplier": 0}):
        assert "CONTRACT_QUOTE_MULTIPLIER_IDENTITY_UNVERIFIED" in contract_sources({**row, **change}, reviews, root=tmp_path, now=NOW)["reasons"]


def test_unadjusted_previous_close_crosscheck_and_source_hash():
    quote = dict(symbol="TEST", provider_status="available", previous_close=100,
                 quote_time=NOW.isoformat(), received_at=NOW.isoformat())
    bar = dict(symbol="TEST", session="2026-09-28", adjustment="NoAdjust", currency="USD",
               source="LONGBRIDGE_HISTORY_MIN_1", open_at="2026-09-28T19:59:00+00:00",
               received_at="2026-09-28T20:01:00+00:00", close=100)
    bar["source_hash"] = common.digest(bar)
    result = build(quote, symbol="TEST", session="2026-09-29", now=NOW, prior_close_bar=bar)
    assert result["price_comparable"]
    assert result["volume_unit"] == "UNKNOWN"
    quote["previous_close"] = 50
    assert not build(quote, symbol="TEST", session="2026-09-29", now=NOW, prior_close_bar=bar)["price_comparable"]
    quote["previous_close"] = 100
    bar["close"] = 101
    assert not build(quote, symbol="TEST", session="2026-09-29", now=NOW, prior_close_bar=bar)["price_comparable"]
