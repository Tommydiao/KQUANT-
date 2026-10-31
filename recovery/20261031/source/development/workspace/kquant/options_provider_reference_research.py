"""Optional P14 replay contract. Never a strict reference or publication input.

No configuration, SDK, journal, or approval writes. Call ``proposal()`` for the
exact method to present to OWNER. ``evaluate_replay`` requires a separately
archived, root-bound receipt even when enabled=True. Archived adapter records
carry source_record={source_path, source_sha256, json_pointer}; the pointed
record excludes source_record itself. Missing native business-date semantics
are a blocker, not permission to infer a date from last-trade/provider time.
"""
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path

from . import options_one_minute as common
from . import options_opening_momentum as s0
from .market_clock import session_bounds_utc
from .options_opening_trend_reference import ROOT, _reviewed_file, source_review
from .options_two_hour_data import sessions_before

METHOD_ID = "PROVIDER_REFERENCE_ASOF_RESEARCH_V1"
_METHOD_JSON = common.canonical({
    "id": METHOD_ID, "default_enabled": False,
    "purpose": "READ_ONLY_PROVIDER_NATIVE_REFERENCE_RESEARCH",
    "canonical_identity": "SOURCE_BOUND_SYMBOL_CURRENCY_XNYS_CALENDAR",
    "previous_close": "NATIVE_MAIN_QUOTE_SECU_QUOTE_PREV_CLOSE_POSITIVE_FINITE",
    "business_date": "SOURCE_REVIEWED_EXPLICIT_NATIVE_BUSINESS_SESSION_ONLY",
    "business_date_inference": False, "prior_day_daily_bar_substitution": False,
    "minutes": "SAME_SYMBOL_CURRENCY_NOADJUST_REGULAR_CLOSED_ASOF_WHOLE_VERSIONS",
    "clock": "EXISTING_ACCEPTED_NTP_INTERVAL_BOUND_V1_REVALIDATED",
    "conflicts": "EXISTING_SOURCE_REVIEWED_CANONICAL_DECISION_OR_BLOCK",
    "price_scale": "KNOWN_SCALE_OR_POTENTIALLY_RELEVANT_UNKNOWN_REQUIRES_REVIEW",
    "timeline_completeness": "ALWAYS_DISCLOSE_NOT_INDEPENDENTLY_PROVEN",
    "previous_close_comparability": "PROVIDER_NATIVE_ASSUMPTION",
    "s0_policy_id": s0.POLICY_ID, "s0_policy_hash": s0.load_policy()["policy_hash"],
    "formula": "UNCHANGED_S0_ISOLATED_PREPARED_INPUTS",
    "checkpoints_deadlines_structure_auxiliary": "UNCHANGED_S0",
    "output": "SEPARATE_METHOD_RULE_HASH_SNAPSHOT_ASSUMPTIONS_EVENTS_GAPS_STRICT_RESULT",
    "contracts": "UNVERIFIED_REFERENCE_ONLY_UNITS_AND_MULTIPLIERS_NOT_ASSUMED",
    "event_policy": "UNCHANGED_GRADED_V2_MAJOR_BLOCKS_REMAIN_EFFECTIVE",
    "evidence_mode": "REPLAY_ONLY_NO_HISTORICAL_LIVE_BACKFILL",
    "future_window_recording": "DEFERRED_RUNTIME_BINDING_AFTER_EXACT_ACCEPTANCE",
    "strict_reference_verified": False, "qualified_publication_enabled": False,
    "qualified_claims_write": False, "verified_statistics_write": False,
    "buy_or_order_enabled": False, "profit_probability_enabled": False,
    "rejection": "PRESERVE_ORIGINAL_STRICT_AND_PARTIAL_OBSERVATION_NO_FALLBACK",
})
RULE_HASH = common.digest(json.loads(_METHOD_JSON))
_ACCEPTANCE_TEXT = (
    "\u63a5\u53d7{hash}\u7684\u4f9b\u5e94\u5546\u539f\u751f\u53c2\u8003\u7814\u7a76\u65b9\u6cd5\uff0c"
    "\u4ec5\u7528\u4e8e\u660e\u793a\u5047\u8bbe\u7684\u53ea\u8bfb\u7814\u7a76\u5019\u9009\uff1b"
    "\u4e0d\u8ba4\u53ef\u5168\u5386\u53f2\u5b8c\u6574\u3001\u4e0d\u4fee\u6539\u539f\u4e25\u683c\u8d44\u683c\uff0c"
    "\u4e0d\u6279\u51c6\u5408\u683c\u4e70\u5165\u6216\u8ba2\u5355\u3002"
)


def proposal():
    """Deterministic proposal JSON/hash, not an acceptance or active config."""
    return {"status": "PROPOSAL_ONLY", "owner_accepted": False, "enabled": False,
            "method": json.loads(_METHOD_JSON), "rule_hash": RULE_HASH,
            "acceptance_text": _ACCEPTANCE_TEXT.format(hash=RULE_HASH)}


def accepted_method(proof, *, root, now):
    """Read the independent original receipt and reply anew on every call."""
    try:
        original = json.loads(_reviewed_file(proof["acceptance_path"], proof["acceptance_sha256"], Path(root)))
        reply = _reviewed_file(original["user_reply_path"], original["user_reply_sha256"], Path(root))
        if (original.get("schema") != METHOD_ID + "_OWNER_RECEIPT"
                or original.get("status") != "ACCEPTED" or original.get("accepted_by") != "OWNER"
                or original.get("source_root") != str(Path(root).resolve())
                or original.get("method") != json.loads(_METHOD_JSON)
                or original.get("method_hash") != RULE_HASH
                or original.get("scope") != "READ_ONLY_RESEARCH_CANDIDATE"
                or reply.decode("utf-8").strip() != proposal()["acceptance_text"]
                or not common.timestamp(original["accepted_at"]) <= now < common.timestamp(original["valid_until"])):
            return None
        return {"acceptance_sha256": proof["acceptance_sha256"], "accepted_at": original["accepted_at"],
                "valid_until": original["valid_until"], "source_root": original["source_root"],
                "method_hash": RULE_HASH, "test_only": original.get("test_only") is True}
    except (AttributeError, OSError, KeyError, TypeError, ValueError, UnicodeError):
        return None


def _archived(record, root):
    proof = record["source_record"]
    value = json.loads(_reviewed_file(proof["source_path"], proof["source_sha256"], Path(root)))
    pointer = proof["json_pointer"]
    if pointer:
        if not isinstance(pointer, str) or not pointer.startswith("/"):
            raise ValueError("SOURCE_LOCATOR_INVALID")
        for part in pointer[1:].split("/"):
            key = part.replace("~1", "/").replace("~0", "~")
            value = value[int(key)] if isinstance(value, list) else value[key]
    if value != {k: v for k, v in record.items() if k != "source_record"}:
        raise ValueError("NATIVE_SOURCE_RECORD_CHANGED")
    return value


def _ordered(record, now):
    return common.timestamp(record["requested_at"]) <= common.timestamp(record["received_at"]) <= now


def _reference(quote, identity, reviews, *, symbol, session, now, root):
    _archived(quote, root)
    _archived(identity, root)
    scope = source_review(reviews.get("instrument_facts", {}).get(symbol), root=Path(root), now=now)
    definition = source_review(reviews.get("previous_close_interface"), root=Path(root), now=now)
    business = source_review(reviews.get("business_date_interface"), root=Path(root), now=now)
    native = quote["sdk_evidence"]
    if (not scope or scope.get("underlying") != symbol
            or scope.get("fact_type") not in {"ORDINARY_EQUITY_IDENTITY", "INSTRUMENT_ASSET_IDENTITY"}
            or identity.get("source") != "LONGBRIDGE_SECURITY_STATIC_INFO"
            or identity.get("symbol") != symbol or not identity.get("provider_symbol")
            or identity.get("canonical_id") != symbol or identity.get("currency") != "USD"
            or identity.get("exchange") != "XNYS" or not _ordered(identity, now)
            or quote.get("symbol") != symbol or quote.get("currency") != identity["currency"]
            or native.get("provider_symbol") != identity["provider_symbol"]):
        raise ValueError("CANONICAL_IDENTITY_CURRENCY_CALENDAR_UNVERIFIED")
    if (quote.get("provider_status") != "available" or native.get("interface") != "QuoteContext.quote"
            or native.get("field") != "secu_quote.prev_close"
            or not definition or definition.get("interface") != "US_SECURITY_QUOTE"
            or definition.get("claim", {}).get("assertion") != "MAIN_QUOTE_PREVIOUS_CLOSE"
            or definition.get("claim", {}).get("field_path") != "secu_quote.prev_close"):
        raise ValueError("NATIVE_MAIN_PREVIOUS_CLOSE_SOURCE_MISSING")
    field = (business or {}).get("business_session_field")
    if (not business or business.get("fact_type") != "PREVIOUS_CLOSE_DEFINITION"
            or business.get("interface") != "US_SECURITY_QUOTE"
            or business.get("business_date_method") != "EXPLICIT_NATIVE_BUSINESS_SESSION"
            or field in {None, "", "timestamp", "quote_time", "last", "last_done", "requested_at", "received_at"}
            or native.get("fields", {}).get(field) != session
            or quote.get("quote_business_session") != session
            or quote.get("reference_session") != sessions_before(date.fromisoformat(session), 1)[0]
            or quote.get("trade_session") != "regular"):
        raise ValueError("REFERENCE_BUSINESS_DATE_AMBIGUOUS")
    opening, closing = session_bounds_utc(date.fromisoformat(session))
    if (not _ordered(quote, now) or common.timestamp(quote["quote_time"]) > common.timestamp(quote["received_at"])
            or not opening <= common.timestamp(quote["requested_at"])
            <= common.timestamp(quote["received_at"]) < closing):
        raise ValueError("REFERENCE_TIME_OR_REGULAR_SESSION_CONFLICT")
    value = quote.get("previous_close")
    if (not common.finite(value) or value <= 0
            or not common.finite(native.get("fields", {}).get("prev_close"))
            or native["fields"]["prev_close"] != value):
        raise ValueError("PREVIOUS_CLOSE_VALUE_INVALID")
    # This is deliberately not PRICE_REFERENCE_V2/V3 and never claims comparable.
    from .options_opening_trend_reference import build
    auxiliary = build(quote, symbol=symbol, session=session, now=now, reviews=reviews, root=Path(root))
    return {"symbol": symbol, "session": session, "currency": identity["currency"],
            "previous_close": value, "received_at": quote["received_at"],
            "source_hash": common.digest(quote), "price_comparable": False,
            "strict_reference_verified": False, "previous_close_comparability": "PROVIDER_NATIVE_ASSUMPTION",
            "research_method_id": METHOD_ID, "rule_hash": RULE_HASH,
            "volume_unit": auxiliary["volume_unit"], "volume_unit_evidence_hash": auxiliary["volume_unit_evidence_hash"],
            "unit_conversion": auxiliary["unit_conversion"], "reference_blockers": [],
            "time_evidence": {"state": "ORDERED", "business_date_inferred": False}}


def _timeline(timeline, *, identity, now, root, reviews):
    _archived(timeline, root)
    if (timeline.get("symbol") != identity["symbol"]
            or timeline.get("provider_symbol") != identity["provider_symbol"] or not _ordered(timeline, now)):
        raise ValueError("ACTION_TIMELINE_IDENTITY_OR_TIME_INVALID")
    raw, parsed = timeline["raw_rows"], timeline["parsed_rows"]
    if not isinstance(raw, list) or not isinstance(parsed, list) or len(raw) != len(parsed):
        raise ValueError("PRICE_SCALE_REVIEW")
    mapping = source_review(reviews.get("action_mapping"), root=Path(root), now=now) if raw else None
    rules = (mapping or {}).get("action_classification_rules", {})
    locators = set()
    for row in parsed:
        # No rows, same-ID dates, or unknowns can disappear in an upstream filter.
        index = row["source_index"]
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(raw) or index in locators:
            raise ValueError("PRICE_SCALE_REVIEW")
        locators.add(index)
        original = raw[index]
        if (row.get("raw_id") != original.get("id") or row.get("query_symbol") != identity["symbol"]
                or row.get("source_locator") != "/raw_rows/" + str(index)
                or row.get("native_category") != original.get("type")
                or row.get("native_date") != original.get("date")
                or row.get("parse_status") != "PARSED"
                or row.get("relevance_to_price_scale") != "NOT_PRICE_SCALE"
                or rules.get(original.get("type")) != "NOT_PRICE_SCALE"):
            raise ValueError("PRICE_SCALE_REVIEW")
    return deepcopy(parsed)


def _minutes(bars, *, symbol, identity, opening, end, now, root, source_decisions):
    from .options_minute_admission import classify
    from .options_minute_decisions import accepted
    from . import options_clock_measurement as clock
    grouped = {}
    for row in bars:
        start = common.timestamp(row["open_at"])
        if not opening <= start < end or common.timestamp(row["received_at"]) > now:
            continue
        _archived(row, root)
        native = row["sdk_evidence"]
        if (row.get("currency") != identity["currency"] or native.get("adjustment") != "NoAdjust"
                or native.get("trade_session") not in {"Intraday", "Regular", "regular", 0}
                or native.get("provider_symbol") != identity["provider_symbol"]):
            raise ValueError("MINUTE_IDENTITY_CURRENCY_NOADJUST_OR_SESSION_INVALID")
        _, reason = classify(row, symbol=symbol, opening=opening, until=end, now=now)
        if reason:
            raise ValueError(reason)
        attachment = native["clock_evidence"]
        at = common.timestamp(native["request_started_at"]) if native.get("interface") == "QuoteContext.candlesticks" else common.timestamp(row["received_at"])
        verified = clock.evaluate(attachment["samples"], proof=attachment["method_acceptance"], root=Path(root), now=at)
        if (attachment.get("source_hash") != common.digest({k: v for k, v in attachment.items() if k != "source_hash"})
                or attachment.get("state") != "VERIFIED_BOUND" or attachment.get("precision_verified") is not True
                or verified["state"] != "VERIFIED_BOUND" or attachment.get("uncertainty_ms") != verified["uncertainty_ms"]
                or not common.timestamp(row["available_at"]) + timedelta(milliseconds=verified["uncertainty_ms"]) <= at
                <= common.timestamp(row["received_at"])):
            raise ValueError("APPROVED_CLOCK_OR_CLOSED_BOUNDARY_UNAVAILABLE")
        grouped.setdefault(start, []).append(row)
    rows = []
    for offset in range(int((end - opening).total_seconds() // 60)):
        start = opening + timedelta(minutes=offset)
        versions = grouped.get(start, [])
        if not versions:
            raise ValueError("CONTIGUOUS_SESSION_MINUTES_MISSING")
        if len({tuple(r[k] for k in ("open", "high", "low", "close")) for r in versions}) > 1:
            decisions = [d for d in source_decisions or [] if d.get("open_at") == start.isoformat()]
            decisions.sort(key=lambda d: d.get("known_at", ""), reverse=True)
            selected = accepted(decisions[0], versions, symbol=symbol, start=start, now=now, root=Path(root)) if decisions else None
            if selected is None:
                raise ValueError("SOURCE_CONFLICT")
        else:
            selected = max(versions, key=lambda r: common.timestamp(r["received_at"]))
        rows.append(selected)
    return rows


def evaluate_replay(*, arguments, quote, identity, timeline, reviews, root=ROOT,
                    enabled=False, method_proof=None, checked_at=None):
    """Return a separate replay envelope; never return a promotable evaluation.

``arguments`` are the unchanged S0 keyword arguments (including strict
reference). The current exact S0 policy is mandatory. ``checked_at`` validates
the receipt; arguments['now'] is the archived market as-of. Nothing is fetched,
persisted, backfilled, or passed to qualification/publication.
"""
    args = deepcopy(arguments)
    args.pop("_prepared", None)
    original = s0.evaluate(**args)
    result = {"schema": METHOD_ID + "_REPLAY", "research_method_id": METHOD_ID, "rule_hash": RULE_HASH,
              "evidence_mode": "REPLAY_ONLY", "live_observed": False, "read_only": True,
              "strict_reference_verified": False, "qualified_signal": False,
              "qualified_publication_enabled": False, "previous_close_comparability": "PROVIDER_NATIVE_ASSUMPTION",
              "strict_s0_state": original["state"], "original_strict_result": deepcopy(original),
              "original_strict_result_hash": common.digest(original), "accepted_method": None,
              "research_computation_state": "DISABLED", "reasons": [], "known_events": [],
              "assumptions": ["PROVIDER_NATIVE_PREVIOUS_CLOSE_NOT_INDEPENDENT_SCALE_CLEARANCE"],
              "gaps": ["COMPANY_ACTION_TIMELINE_COMPLETENESS_NOT_INDEPENDENTLY_PROVEN"],
              "contract_reference_status": "UNVERIFIED_REFERENCE_ONLY",
              "event_policy": "GRADED-V2_MAJOR_BLOCKS_REMAIN_EFFECTIVE"}

    def finish():
        result["snapshot_id"] = common.digest(result)
        return result

    if enabled is not True:
        result["reasons"] = ["METHOD_DEFAULT_DISABLED"]
        return finish()
    try:
        now = common.timestamp(args["now"])
        checked = common.timestamp(checked_at or datetime.now(UTC))
        receipt = accepted_method(method_proof, root=root, now=checked)
        if receipt is None:
            result["reasons"] = ["EXACT_INDEPENDENT_OWNER_METHOD_ACCEPTANCE_MISSING"]
            return finish()
        result["accepted_method"] = receipt
        result["test_only"] = receipt["test_only"]
        result["research_computation_state"] = "INCOMPLETE"
        policy = s0.load_policy()
        if (args.get("policy", policy) != policy or policy["policy_hash"] != json.loads(_METHOD_JSON)["s0_policy_hash"]):
            raise ValueError("ORIGINAL_S0_POLICY_CHANGED")
        opening, closing = map(common.timestamp, (args["opening"], args["closing"]))
        session = opening.astimezone(common.NY).date().isoformat()
        if checked < now or (opening, closing) != session_bounds_utc(date.fromisoformat(session)):
            raise ValueError("CALENDAR_OR_ASOF_INVALID")
        end = common.timestamp(args["checkpoint"]) if args.get("checkpoint") else opening + timedelta(minutes=int((now - opening).total_seconds() // 300) * 5)
        if (end - opening).total_seconds() / 60 not in policy["checkpoint_minutes"] or end > now:
            raise ValueError("ORIGINAL_CHECKPOINT_NOT_READY")
        reference = _reference(quote, identity, reviews, symbol=args["symbol"], session=session, now=now, root=root)
        result["known_events"] = deepcopy(timeline.get("parsed_rows", []))
        _timeline(timeline, identity=identity, now=now, root=root, reviews=reviews)
        rows = _minutes(args["bars"], symbol=args["symbol"], identity=identity, opening=opening, end=end,
                        now=now, root=root, source_decisions=args.get("source_decisions"))
        check = {"state": "COMPLETE", "expected_minutes": len(rows), "valid_minutes": len(rows), "missing_slots": []}
        # Only the private formula preparation bypasses the *strict* reference
        # gate. Its reference remains non-comparable; sanitize before exposure.
        computed = s0.evaluate(**{**args, "policy": policy, "reference": reference,
            "_prepared": (rows, [], check, True, s0.price_aggregate(rows))})
        formula_state = computed.pop("state")
        for key in ("event_id", "evaluation_id", "policy_snapshot", "runtime_mode", "research_strategy"):
            computed.pop(key, None)
        computed["input_checks"]["reference"] = {"state": "PROVIDER_NATIVE_ASSUMPTION", "strict_reference_verified": False}
        result.update(formula_state=formula_state, formula_result=computed,
                      research_computation_state="COMPLETE" if formula_state == "NUMERIC_PASS" else
                      "NO_TRIGGER" if formula_state == "NO_TRIGGER" else "INCOMPLETE",
                      reasons=list(computed["reasons"]))
    except (AttributeError, OSError, KeyError, IndexError, TypeError, ValueError, OverflowError) as exc:
        result["research_computation_state"] = "INCOMPLETE"
        result["reasons"] = [str(exc) if isinstance(exc, ValueError) else "RESEARCH_SOURCE_OR_INPUT_UNAVAILABLE"]
    return finish()


def project_replay(strict_result, replay):
    """Read-only binding. No strict state, counts, claims, or qualifier changes."""
    try:
        if (replay.get("schema") != METHOD_ID + "_REPLAY" or replay.get("rule_hash") != RULE_HASH
                or replay.get("research_method_id") != METHOD_ID
                or replay.get("snapshot_id") != common.digest({k: v for k, v in replay.items() if k != "snapshot_id"})
                or replay.get("original_strict_result") != strict_result
                or replay.get("original_strict_result_hash") != common.digest(strict_result)
                or replay.get("strict_s0_state") != strict_result["state"]
                or replay.get("evidence_mode") != "REPLAY_ONLY" or replay.get("live_observed") is not False
                or replay.get("strict_reference_verified") is not False or replay.get("qualified_signal") is not False
                or replay.get("qualified_publication_enabled") is not False):
            raise ValueError("RESEARCH_PROJECTION_BINDING_INVALID")
        return deepcopy(replay)
    except (AttributeError, KeyError, TypeError, ValueError):
        return {"research_method_id": METHOD_ID, "rule_hash": RULE_HASH, "research_computation_state": "UNAVAILABLE",
                "reasons": ["RESEARCH_PROJECTION_BINDING_INVALID"], "strict_reference_verified": False,
                "qualified_signal": False, "read_only": True, "evidence_mode": "REPLAY_ONLY"}


if __name__ == "__main__":
    print(json.dumps(proposal(), ensure_ascii=True, sort_keys=True, indent=2))
