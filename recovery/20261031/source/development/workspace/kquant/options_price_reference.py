"""Independent previous-close semantics; minute close is diagnostic, not equality proof."""
from datetime import date

from . import options_one_minute as common
from .options_two_hour_data import sessions_before
from .options_opening_trend_reference import ROOT, source_review, build as auxiliary_build

VERSION = "PRICE_REFERENCE_V2"


def build(quote, *, symbol, session, now, reviews=None, root=ROOT, prior_close_bar=None):
    reviews = reviews or {}
    # Preserve reviewed auxiliary conversions without using their history as a price gate.
    auxiliary = auxiliary_build(quote, symbol=symbol, session=session, now=now, reviews=reviews, root=root)
    binding = quote.get("session_price_binding")
    interface = reviews.get("previous_close_interface")
    freshly_verified = None
    if isinstance(interface, dict) and interface.get("contract_version") == "INTERFACE_FACT_V1":
        from .options_price_facts import bind, prepare_binding
        binding = prepare_binding(bind(quote, symbol=symbol, session=session, now=now, reviews=reviews, root=root))
        # bind just read the original source bytes and checked their semantics.
        # Do not rebuild that same result; model.valid still rechecks the bytes
        # before computation. Imported/configured bindings take the full path.
        freshly_verified = (binding["status"] == "VERIFIED"
                            and common.timestamp(binding["known_at"]) <= now
                            < common.timestamp(binding["valid_until"]))
        quote = {**quote, "session_price_binding": binding}
    if isinstance(binding, dict):
        from .options_price_facts import valid as binding_valid
        accepted = (freshly_verified if freshly_verified is not None else
                    binding_valid(binding, symbol=symbol, session=session, now=now, root=root))
        value = {**auxiliary, "contract_version": "PRICE_REFERENCE_V3", "canonical_id": symbol,
            "session": session, "reference_session": binding["reference_session"], "currency": binding["currency"],
            "previous_close": binding.get("previous_close") if accepted else None,
            "price_comparable": accepted, "reference_blockers": [] if accepted else (binding.get("reasons") or ["BINDING_INVALID"]),
            "session_price_binding": binding, "known_at": binding["known_at"], "raw_quote": quote,
            "price_basis_method": binding["method"]}
        value["reference_hash"] = common.digest(value)
        return value
    previous = sessions_before(date.fromisoformat(session), 1)[0]
    field = source_review(reviews.get("previous_close_interface"), root=root, now=now)
    if "price_comparability_by_symbol_session" in reviews:
        sessions = reviews["price_comparability_by_symbol_session"]
        symbols = sessions.get(session, {}) if isinstance(sessions, dict) else {}
        scale_record = symbols.get(symbol) if isinstance(symbols, dict) else None
    else:
        scale_record = reviews.get("price_comparability")
    scale = source_review(scale_record, root=root, now=now)
    reasons = []
    identity = quote.get("symbol") == symbol and quote.get("provider_status") == "available"
    if not identity:
        reasons.append("REFERENCE_IDENTITY_UNVERIFIED")
    ordered, trade_session = False, None
    try:
        received = common.timestamp(quote["received_at"])
        provided = common.timestamp(quote["quote_time"])
        requested = common.timestamp(quote["requested_at"])
        ordered = requested <= received <= now and provided <= received
        trade_session = provided.astimezone(common.NY).date().isoformat()
    except (KeyError, TypeError, ValueError):
        pass
    if not ordered:
        reasons.append("REFERENCE_TIME_CONFLICT")
    field_ok = bool(field and field.get("interface") == "US_SECURITY_QUOTE"
                    and field.get("field") == "prev_close"
                    and field.get("meaning") == "PREVIOUS_REGULAR_SESSION_CLOSE")
    explicit_business = quote.get("quote_business_session")
    business_ok = field_ok and (trade_session == session or (
        explicit_business == session and field.get("business_session_field") == "quote_business_session"))
    if quote.get("reference_session") not in (None, previous):
        business_ok = False
    if not business_ok:
        reasons.append("REFERENCE_BUSINESS_DATE_AMBIGUOUS")
    currency = quote.get("currency")
    currency_proof = quote.get("currency_evidence", {})
    currency_ok = (currency == "USD" and currency_proof.get("currency") == currency
                   and currency_proof.get("symbol") == symbol
                   and currency_proof.get("source") == "LONGBRIDGE_SECURITY_STATIC_INFO"
                   and currency_proof.get("source_hash") == common.digest(
                       {k: v for k, v in currency_proof.items() if k != "source_hash"}))
    if not currency_ok:
        reasons.append("REFERENCE_CURRENCY_UNVERIFIED")
    scale_ok = bool(scale and scale.get("interface") == "US_SECURITY_QUOTE_AND_CANDLESTICK"
                    and scale.get("price_basis") == "NoAdjust"
                    and scale.get("symbol") == symbol and scale.get("session") == session
                    and scale.get("corporate_action_comparability") == "COMPARABLE")
    if not scale_ok:
        reasons.append("ADJUSTMENT_REVIEW")
    if not common.finite(quote.get("previous_close")) or quote["previous_close"] <= 0:
        reasons.append("PREVIOUS_CLOSE_VALUE_INVALID")
    value = {**auxiliary, "contract_version": VERSION, "canonical_id": symbol,
        "currency": currency, "reference_session": previous,
        "provider_previous_close": quote.get("previous_close"),
        "previous_last_minute_close": (prior_close_bar or {}).get("close"),
        "prior_close_evidence": prior_close_bar or {},
        "previous_close": quote.get("previous_close") if identity and business_ok else None,
        "price_comparable": scale_ok and currency_ok,
        "price_basis_evidence_hash": scale.get("source_sha256") if scale_ok else None,
        "price_basis_method": VERSION, "reference_blockers": reasons,
        "business_date_proof": field, "price_scale_proof": scale,
        "known_at": quote.get("received_at"), "queried_at": quote.get("requested_at"),
        "source_hash": common.digest(quote), "raw_quote": quote,
        "time_evidence": {**auxiliary["time_evidence"], "state": "ORDERED" if ordered else "CONFLICT"}}
    value["reference_hash"] = common.digest(value)
    return value


def valid(reference, *, symbol, session, now, root=None):
    try:
        if reference.get("contract_version") == "PRICE_REFERENCE_V3":
            from .options_price_facts import valid as binding_valid
            return (reference.get("reference_hash") == common.digest(
                        {k: v for k, v in reference.items() if k != "reference_hash"})
                    and reference.get("canonical_id") == symbol and reference.get("session") == session
                    and not reference.get("reference_blockers")
                    and binding_valid(reference.get("session_price_binding", {}), symbol=symbol,
                                     session=session, now=now, root=root or ROOT))
        return (reference.get("contract_version") == VERSION
                and reference.get("canonical_id") == symbol and reference.get("session") == session
                and reference.get("reference_session") == sessions_before(date.fromisoformat(session), 1)[0]
                and not reference.get("reference_blockers") and reference.get("currency") == "USD"
                and source_review(reference.get("business_date_proof"), root=root or ROOT, now=now) is not None
                and source_review(reference.get("price_scale_proof"), root=root or ROOT, now=now) is not None
                and reference.get("price_comparable") is True
                and reference.get("reference_hash") == common.digest(
                    {k: v for k, v in reference.items() if k != "reference_hash"})
                and common.timestamp(reference["known_at"]) <= now
                and common.finite(reference.get("previous_close")) and reference["previous_close"] > 0)
    except (KeyError, TypeError, ValueError):
        return False
