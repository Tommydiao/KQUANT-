"""Shared interface facts, persistent instruments, and automatic session bindings.

These are research evidence in the existing journal, never owner approvals.
"""
from contextlib import closing
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3

from . import options_one_minute as common
from .options_two_hour_data import sessions_before
from .options_opening_trend_reference import ROOT, source_review

INSTRUMENT = "PRICE_INSTRUMENT_FACT_V1"
BINDING = "SESSION_PRICE_BINDING_V1"
PRICE_FACT_BATCH_BOUND = 16


def interface_fact(row, *, now, root=ROOT, assertion=None):
    proof = source_review(row, now=now, root=root)
    if not proof or proof.get("contract_version") != "INTERFACE_FACT_V1":
        return None
    claim = proof.get("claim", {})
    if (not claim or proof.get("claim_hash") != common.digest(claim)
            or not claim.get("field_path") or not claim.get("assertion")
            or assertion and claim["assertion"] != assertion):
        return None
    if claim.get("assertion") == "MAIN_QUOTE_PREVIOUS_CLOSE" and (
            claim.get("field_path") != "secu_quote.prev_close"
            or "prev_close" not in proof.get("excerpt", "")
            or "昨收价" not in proof.get("excerpt", "")):
        return None
    return proof


def _persist(path, kind, value):
    body = {**value, "kind": kind}
    body["fact_hash"] = common.digest(body)
    with closing(sqlite3.connect(path, timeout=.05)) as db, db:
        db.execute("""INSERT OR IGNORE INTO two_hour_jobs VALUES
            (?,?,?,?,?,?,'COMPLETED',NULL,NULL,0,NULL,NULL,?)""",
            (body["fact_hash"], body.get("session", "PERSISTENT"), body["symbol"], kind,
             body["known_at"], body["valid_until"], common.canonical(body)))
    return body


def instrument(quote, *, now, reviews, root=ROOT):
    native = quote.get("currency_evidence", {})
    symbol = quote.get("symbol")
    identity = bool(symbol and native.get("symbol") == symbol and native.get("provider_symbol")
        and native.get("source") == "LONGBRIDGE_SECURITY_STATIC_INFO"
        and native.get("source_hash") == common.digest({k: v for k, v in native.items() if k != "source_hash"}))
    currency = native.get("currency") if identity else None
    scope = reviews.get("instrument_facts", {}).get(symbol)
    scope = source_review(scope, now=now, root=root)
    asset = scope.get("asset_type") if scope and scope.get("underlying") == symbol else "UNKNOWN"
    acquired = common.timestamp(native.get("received_at") or quote.get("received_at") or now.isoformat())
    return dict(symbol=symbol, provider_symbol=native.get("provider_symbol"),
        native_identity=native, currency=currency, asset_type=asset,
        classification_proof=scope, identity_verified=identity, known_at=acquired.isoformat(),
        valid_until=min(acquired + timedelta(days=7), common.timestamp(scope["valid_until"])).isoformat()
            if scope else (acquired + timedelta(days=7)).isoformat(),
        status="IDENTITY_CURRENCY_VERIFIED" if identity and currency else "UNVERIFIED",
        classification_status="VERIFIED" if scope and asset != "UNKNOWN" else "PENDING_ASSET_TYPE_FACT")


def bind(quote, *, symbol, session, now, reviews, root=ROOT):
    """Apply shared methods to one real asset/day; no daily manual COMPARABLE flag."""
    asset = instrument(quote, now=now, reviews=reviews, root=root)
    previous = sessions_before(date.fromisoformat(session), 1)[0]
    definition = interface_fact(reviews.get("previous_close_interface"), now=now, root=root,
                                assertion="MAIN_QUOTE_PREVIOUS_CLOSE")
    method = interface_fact(reviews.get("price_binding_method") or reviews.get("price_basis_interface"), now=now, root=root,
                            assertion="QUOTE_AND_NO_ADJUST_PRICE_BASIS")
    raw_actions = reviews.get("instrument_price_actions", {}).get(symbol)
    from .options_price_action_source import FACT, current_fact, valid_fact
    if raw_actions is None:
        raw_actions = current_fact(root, symbol=symbol, session=session, previous=previous, now=now,
                                  method=reviews.get("company_action_coverage_method"))
    actions = (valid_fact(raw_actions, symbol=symbol, previous=previous, session=session, now=now, root=root)
               if isinstance(raw_actions, dict) and raw_actions.get("contract_version") == FACT
               else source_review(raw_actions, now=now, root=root))
    reasons = []
    if quote.get("symbol") != symbol or quote.get("provider_status") != "available" or not asset["identity_verified"]:
        reasons.append("INSTRUMENT_IDENTITY_UNVERIFIED")
    if asset["currency"] != "USD" or quote.get("currency") != asset["currency"]:
        reasons.append("REFERENCE_CURRENCY_UNVERIFIED")
    try:
        requested, received, trade = (common.timestamp(quote[k]) for k in ("requested_at", "received_at", "quote_time"))
        current = trade.astimezone(common.NY).date().isoformat() == session
        if not requested <= received <= now or trade > received:
            reasons.append("REFERENCE_TIME_CONFLICT")
    except (KeyError, TypeError, ValueError):
        current = False
        reasons.append("REFERENCE_TIME_CONFLICT")
    if not definition:
        reasons.append("PREVIOUS_CLOSE_INTERFACE_FACT_MISSING")
    if not current:
        reasons.append("PREPARED_PENDING_CURRENT_SESSION")
    if not method or method.get("price_basis") != "NoAdjust":
        reasons.append("PRICE_BASIS_METHOD_FACT_MISSING")
    action_ok = bool(actions and actions.get("underlying") == symbol
        and actions.get("price_scale_state") == "UNCHANGED"
        and actions.get("complete") is True
        and actions.get("coverage_from_session", "9999") <= previous
        and actions.get("coverage_through_session", "") >= session)
    if not action_ok:
        reasons.append("INSTRUMENT_PRICE_ACTION_COVERAGE_MISSING")
    value = quote.get("previous_close")
    if not common.finite(value) or value <= 0:
        reasons.append("PREVIOUS_CLOSE_VALUE_INVALID")
    if quote.get("reference_session") not in (None, previous):
        reasons.append("REFERENCE_SESSION_MISMATCH")
    proofs = [p for p in (definition, method, actions) if p]
    try:
        acquired = common.timestamp(quote["received_at"])
    except (KeyError, TypeError, ValueError):
        acquired = now
    known = max([acquired] + [common.timestamp(p.get("known_at", p.get("reviewed_at", acquired.isoformat()))) for p in proofs])
    expires = min([acquired + timedelta(days=1)] + [common.timestamp(p["valid_until"]) for p in proofs])
    return dict(symbol=symbol, session=session, reference_session=previous,
        contract_version=BINDING, method="LIVE_MAIN_QUOTE_WITH_REVIEWED_PRICE_BASIS",
        previous_close=value if current else None, observed_provider_previous_close=value,
        currency=asset["currency"], instrument=asset,
        interface_fact=definition, price_basis_method=method, action_coverage=actions,
        raw_quote=deepcopy({k: v for k, v in quote.items() if k != "session_price_binding"}),
        known_at=known.isoformat(), valid_until=expires.isoformat(),
        status="VERIFIED" if not reasons else "PREPARED_WITH_GAPS", reasons=sorted(set(reasons)))


def persist_binding(path, value):
    return persist_bindings(path, [value])[0]


def persist_bindings(path, values):
    if len(values) > PRICE_FACT_BATCH_BOUND:
        raise ValueError("PRICE_FACT_BATCH_BOUND_EXCEEDED")
    if not values:
        return []
    prepared = [prepare_binding(value) for value in values]
    # Both facts share one small transaction; a missing store must not be created.
    uri = Path(path).absolute().as_uri() + "?mode=rw"
    from .options_input_commit_fence import commit_fence
    with commit_fence(), closing(sqlite3.connect(uri, uri=True, timeout=.05)) as db, db:
        for value in prepared:
            persist_prepared_in_transaction(db, value)
    return prepared


def prepare_binding(value):
    """Hash facts without taking a second write lock during pure calculation."""
    asset = {**value["instrument"], "kind": INSTRUMENT}
    asset["fact_hash"] = common.digest(asset)
    body = {**value, "kind": BINDING, "instrument_fact_hash": asset["fact_hash"]}
    body["fact_hash"] = common.digest(body)
    return body


def persist_prepared_in_transaction(db, value):
    from .options_input_commit_fence import require_fence
    require_fence()  # Caller must hold it through COMMIT, not just these INSERTs.
    asset = {**value["instrument"], "kind": INSTRUMENT}
    asset["fact_hash"] = common.digest(asset)
    for body in (asset, value):
        if body["fact_hash"] != common.digest({k: v for k, v in body.items() if k != "fact_hash"}):
            raise ValueError("PRICE_FACT_HASH_CHANGED_BEFORE_COMMIT")
        db.execute("""INSERT OR IGNORE INTO two_hour_jobs VALUES
            (?,?,?,?,?,?,'COMPLETED',NULL,NULL,0,NULL,NULL,?)""",
            (body["fact_hash"], body.get("session", "PERSISTENT"), body["symbol"], body["kind"],
             body["known_at"], body["valid_until"], common.canonical(body)))


def valid(value, *, symbol, session, now, root=ROOT):
    try:
        if (value.get("kind") != BINDING or value.get("status") != "VERIFIED"
                or value.get("symbol") != symbol or value.get("session") != session
                or not common.timestamp(value["known_at"]) <= now < common.timestamp(value["valid_until"])
                or value.get("fact_hash") != common.digest({k: v for k, v in value.items() if k != "fact_hash"})):
            return False
        reviews = dict(previous_close_interface=value["interface_fact"], price_binding_method=value["price_basis_method"],
                       instrument_price_actions={symbol: value["action_coverage"]})
        return bind(value["raw_quote"], symbol=symbol, session=session, now=now, reviews=reviews, root=root)["status"] == "VERIFIED"
    except (KeyError, TypeError, ValueError):
        return False
