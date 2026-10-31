"""Source-bound reference assembly. Quotes never imply verified volume units."""
from hashlib import sha256
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse
import json
import os
from stat import S_ISREG
from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache

from . import options_one_minute as common
from .market_clock import session_bounds_utc
from .options_two_hour_data import sessions_before

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "config/review_acceptances/options_opening_trend_reference_sources.json"


def source_review(row, *, root=ROOT, now):
    """Only an explicitly reviewed, unchanged official source can supply a fact."""
    if not isinstance(row, dict):
        return None
    try:
        if (row.get("status") != "APPROVED" or not row.get("reviewer")
                or row["reviewer"] == "local@kquant.local"
                or not common.timestamp(row["reviewed_at"]) <= now < common.timestamp(row["valid_until"])):
            return None
        kind = row.get("source_kind", "OFFICIAL_DOCUMENT")
        if kind == "OFFICIAL_DOCUMENT":
            url = urlparse(row["source_url"])
            if (url.scheme != "https" or url.hostname not in {"open.longbridge.com", "open.longbridge.cn"}
                    or url.username or url.password or url.port not in (None, 443)):
                return None
        elif kind in {"OFFICIAL_INTERFACE_FACT", "OFFICIAL_SERIES_RECORD"}:
            url = urlparse(row["source_url"])
            fact = row.get("fact_type")
            authorities = {"CANDLESTICK_UNITS": {"open.longbridge.com", "open.longbridge.cn"},
                           "OPTION_DEPTH_UNITS": {"open.longbridge.com", "open.longbridge.cn"},
                           "OPTION_QUOTE_MULTIPLIER": {"open.longbridge.com", "open.longbridge.cn"},
                           "OPTION_STANDARD_CHAIN": {"open.longbridge.com", "open.longbridge.cn"},
                           "EQUITY_STANDARD_SPECIFICATION": {"www.theocc.com"},
                           "ORDINARY_EQUITY_IDENTITY": {"www.sec.gov", "data.sec.gov"},
                           "INSTRUMENT_ASSET_IDENTITY": {"www.sec.gov", "data.sec.gov", "www.nasdaq.com", "www.nyse.com"},
                           "OPTION_ASSET_SPECIFICATION": {"www.theocc.com", "www.optionseducation.org"},
                           "PREVIOUS_CLOSE_DEFINITION": {"open.longbridge.com", "open.longbridge.cn"},
                           "OPTION_SERIES_DELIVERABLE": {"www.theocc.com", "infomemo.theocc.com"}}
            if (fact not in authorities or url.scheme != "https" or url.hostname not in authorities[fact]
                    or url.username or url.password or url.port not in (None, 443)
                    or (kind == "OFFICIAL_SERIES_RECORD") != (fact == "OPTION_SERIES_DELIVERABLE")
                    or row.get("review_method") not in {"NAMED_DOCUMENT_REVIEW", "PROGRAMMATIC_DOCUMENT_REVIEW"}
                    or row.get("reviewer") in {"OWNER", "AUTOMATED", "VERIFIED"}):
                return None
        elif kind != "FORMAL_PROVIDER_REPLY":
            return None
        raw = _reviewed_file(row["source_path"], row["source_sha256"], root)
        if not row.get("excerpt") or row["excerpt"] not in raw.decode("utf-8"):
            return None
        if kind == "FORMAL_PROVIDER_REPLY" and not _formal_reply_review(row, root=root, now=now):
            return None
        return row
    except (OSError, KeyError, ValueError, TypeError, UnicodeError, AttributeError):
        return None


@lru_cache(maxsize=16)
def _canonical_source_root(absolute_root):
    return absolute_root.resolve()


def _reviewed_file(relative_path, digest, root):
    canonical = _canonical_source_root(root.absolute())
    # Resolve the child anew. Retargeting a root/child alias outside the original
    # root fails closed; no source content or successful hash check is cached.
    path = (root / relative_path).resolve()
    if not path.is_relative_to(canonical):
        raise ValueError("SOURCE_ARCHIVE_INVALID")
    # Bound the actual read, not a size observed before a concurrent rewrite.
    with path.open("rb") as stream:
        if not S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("SOURCE_ARCHIVE_INVALID")
        # Small facts must not allocate the entire 2 MiB validation limit.
        remaining, chunks = 2097153, []
        while remaining:
            chunk = stream.read(min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
    if not 0 < len(raw) <= 2097152:
        raise ValueError("SOURCE_ARCHIVE_INVALID")
    if sha256(raw).hexdigest() != digest:
        raise ValueError("SOURCE_ARCHIVE_CHANGED")
    return raw


def _formal_reply_review(row, *, root, now):
    # A config flag cannot replace the original reply or its independent review.
    review = json.loads(_reviewed_file(row["authenticity_review_path"], row["authenticity_review_sha256"], root))
    issued = common.timestamp(review["issued_at"])
    reviewed = common.timestamp(review["reviewed_at"])
    return (review.get("status") == "ACCEPTED" and review.get("provider") == "LONGBRIDGE"
            and review.get("channel") in {"SUPPORT_TICKET", "EMAIL"}
            and bool(review.get("reference_id")) and bool(review.get("issuer_origin"))
            and review.get("method") == "ORIGINAL_PROVIDER_CHANNEL_MANUALLY_VERIFIED"
            and review.get("reviewer") == row["reviewer"]
            and reviewed == common.timestamp(row["reviewed_at"])
            and issued <= reviewed <= now
            and review.get("source_sha256") == row["source_sha256"]
            and isinstance(review.get("applicable_interfaces"), list)
            and row.get("interface") in review["applicable_interfaces"])


def load_reviews(path=REVIEW):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            return {}
        contracts = ROOT / "config/review_acceptances/options_contract_units_sources.json"
        if path.resolve() not in {REVIEW.resolve(), contracts.resolve()}:
            return value
        files = (REVIEW, contracts)
        merged, hashes = {}, {}
        for file in files:
            raw = file.read_bytes()
            for key, entry in json.loads(raw).items():
                if key in merged and merged[key] != entry:
                    raise ValueError("SOURCE_BUNDLE_KEY_CONFLICT: " + key)
                merged[key] = entry
            hashes[file.relative_to(ROOT).as_posix()] = sha256(raw).hexdigest()
        merged["source_bundle"] = {"files": hashes, "sha256": common.digest(hashes),
            "consumer_contract": "SHARED_FACTS_WITH_SEPARATE_PRICE_AND_CONTRACT_ROLES"}
        return merged
    except (OSError, ValueError):
        return {}


def contract_proofs(row, reviews):
    """Bind reusable interface facts and positive series records to native identity."""
    reviews = reviews if isinstance(reviews, dict) else {}
    contract_id = row.get("contract_id")
    deliverables = reviews.get("deliverables", {})
    multipliers = reviews.get("quote_multipliers", {})
    deliverable = deliverables.get(contract_id) if isinstance(deliverables, dict) else None
    multiplier = multipliers.get(contract_id) if isinstance(multipliers, dict) else None
    if multiplier is None:
        shared = reviews.get("quote_multiplier_interface")
        if isinstance(shared, dict) and shared.get("fact_type") == "OPTION_QUOTE_MULTIPLIER":
            multiplier = {**shared, "contract_symbol": contract_id, "underlying": row.get("underlying"),
                          "multiplier": row.get("raw_multiplier"), "binding_method": "NATIVE_RESPONSE_FIELD"}
    if deliverable is None:
        chain = row.get("provider_standard_evidence")
        facts = reviews.get("provider_standard_chain", {})
        scope = (reviews.get("instrument_facts", {}).get(row.get("underlying"))
                 or reviews.get("ordinary_equities", {}).get(row.get("underlying")))
        if chain and facts and scope:
            specification = facts.get("asset_specifications", {}).get(scope.get("asset_type"))
            if specification is None and scope.get("asset_type") == "US_ORDINARY_EQUITY":
                specification = facts.get("equity_specification")
            deliverable = {"source_kind": "PROVIDER_STANDARD_CHAIN_V1", "chain_evidence": chain,
                "standard_definition": facts.get("standard_definition"),
                "equity_specification": specification, "equity_scope": scope,
                "contract_symbol": contract_id, "underlying": row.get("underlying"),
                "right": row.get("right"), "expiry_date": row.get("expiry_date"), "strike": row.get("strike"),
                "deliverable_type": "STANDARD", "adjusted": False,
                "valid_until": min(facts.get("standard_definition", {}).get("valid_until", ""),
                    (specification or {}).get("valid_until", ""), scope.get("valid_until", ""))}
    if deliverable is None:
        matches = []
        for proof in reviews.get("series_records", []) or []:
            if not isinstance(proof, dict) or proof.get("source_kind") != "OFFICIAL_SERIES_RECORD":
                continue
            for record in proof.get("records", []) or []:
                if (isinstance(record, dict) and record.get("contract_symbol") == contract_id
                        and all(record.get(k) == row.get(k) for k in ("underlying", "right", "expiry_date", "strike"))):
                    fields = {k: record.get(k) for k in ("contract_symbol", "underlying", "right", "expiry_date",
                              "strike", "deliverable_type", "adjusted", "share_quantity", "cash_amount", "deliverable_security")}
                    matches.append({**proof, **fields, "series_record": record,
                                    "binding_method": "EXPLICIT_OFFICIAL_SERIES_RECORD"})
        if len(matches) == 1:
            deliverable = matches[0]
    return {"depth_units": reviews.get("depth_units"), "deliverable": deliverable,
            "quote_multiplier": multiplier}


def reviewed_contract_proof(proof, *, root=ROOT, now):
    if isinstance(proof, dict) and proof.get("source_kind") == "PROVIDER_STANDARD_CHAIN_V1":
        return _provider_standard(proof, root=root, now=now)
    accepted = source_review(proof, root=root, now=now)
    if accepted and accepted.get("source_kind") == "OFFICIAL_SERIES_RECORD":
        try:
            raw = json.loads(_reviewed_file(proof["source_path"], proof["source_sha256"], root))
            record = proof["series_record"]
            if (raw.get("schema") != "OCC_EXPLICIT_SERIES_JSON_V1" or record not in raw["records"]
                    or record.get("deliverable_type") != "STANDARD" or record.get("adjusted") is not False
                    or record.get("share_quantity") != 100 or record.get("cash_amount") != 0
                    or record.get("deliverable_security") != record.get("underlying")):
                return None
        except (KeyError, TypeError, ValueError, OSError):
            return None
    return accepted


def _provider_standard(proof, *, root, now):
    try:
        definition = source_review(proof.get("standard_definition"), root=root, now=now)
        spec = source_review(proof.get("equity_specification"), root=root, now=now)
        scope = source_review(proof.get("equity_scope"), root=root, now=now)
        response = proof["chain_evidence"]["response"]
        row = proof["chain_evidence"]["row"]
        field = "call_symbol" if proof["right"] == "CALL" else "put_symbol" if proof["right"] == "PUT" else None
        if (not definition or definition.get("fact_type") != "OPTION_STANDARD_CHAIN"
                or not spec or spec.get("fact_type") not in {"EQUITY_STANDARD_SPECIFICATION", "OPTION_ASSET_SPECIFICATION"}
                or not scope or scope.get("fact_type") not in {"ORDINARY_EQUITY_IDENTITY", "INSTRUMENT_ASSET_IDENTITY"}
                or any(p.get("source_kind") != "OFFICIAL_INTERFACE_FACT" for p in (definition, spec, scope))
                or scope.get("underlying") != proof["underlying"]
                or scope.get("asset_type") not in {"US_ORDINARY_EQUITY", "US_ADR", "US_ETF"}
                or (scope.get("asset_type") != "US_ORDINARY_EQUITY" and spec.get("asset_type") != scope.get("asset_type"))
                or not field or response.get("source") != "longbridge_option_chain"
                or response.get("source_hash") != common.digest({k: v for k, v in response.items() if k != "source_hash"})
                or response.get("symbol") != proof["underlying"] or response.get("expiry_date") != proof["expiry_date"]
                or not response.get("sdk_version") or response.get("sdk_interface") != "QuoteContext.option_chain_info_by_date"
                or not common.timestamp(response["requested_at"]) <= common.timestamp(response["received_at"]) <= now
                or row not in response["contracts"] or row.get(field) != proof["contract_symbol"]
                or row.get("strike_price") != proof["strike"] or row.get("is_standard") is not True
                or row.get("raw_standard") is not True or row.get("raw_standard_type") != "bool"):
            return None
        return proof
    except (KeyError, TypeError, ValueError):
        return None


def contract_sources(row, reviews, *, now, binding=None, root=ROOT):
    """Recheck the selected source identities without fetching a new quote."""
    reasons, accepted = [], {}
    bound = binding if binding is not None else {
        "depth_units": row.get("quantity_evidence"),
        "deliverable": row.get("deliverable_evidence"),
        "quote_multiplier": row.get("multiplier_evidence")}
    reviews = reviews if isinstance(reviews, dict) else {}
    current = contract_proofs(row, reviews)
    for role, proof in current.items():
        original = bound.get(role) if isinstance(bound, dict) else None
        if not isinstance(original, dict) or not original:
            reasons.append("CONTRACT_" + role.upper() + "_SOURCE_MISSING")
        elif not isinstance(proof, dict) or common.digest(original) != common.digest(proof):
            reasons.append("CONTRACT_" + role.upper() + "_SOURCE_CHANGED")
        elif reviewed_contract_proof(proof, root=root, now=now) is None:
            reasons.append("CONTRACT_" + role.upper() + "_SOURCE_UNAVAILABLE")
        else:
            accepted[role] = proof
    units, deliverable = accepted.get("depth_units", {}), accepted.get("deliverable", {})
    factor = units.get("raw_units_per_contract")
    if units:
        valid = (units.get("interface") == "US_OPTION_DEPTH" and common.finite(factor) and factor > 0
                 and row.get("size_unit_status") == "VERIFIED_CONTRACTS")
        for side in ("bid", "ask"):
            raw = row.get("raw_" + side + "_size")
            valid = valid and common.finite(raw) and row.get(side + "_size") == raw / factor
        if not valid:
            reasons.append("CONTRACT_DEPTH_UNIT_CONVERSION_UNVERIFIED")
    if deliverable and not (
            deliverable.get("contract_symbol") == row.get("contract_id")
            and deliverable.get("underlying") == row.get("underlying")
            and deliverable.get("deliverable_type") == "STANDARD" and deliverable.get("adjusted") is False
            and row.get("deliverable") == "STANDARD" and row.get("adjusted") is False):
        reasons.append("CONTRACT_DELIVERABLE_IDENTITY_UNVERIFIED")
    multiplier = accepted.get("quote_multiplier", {})
    if multiplier and not multiplier_matches(multiplier, row):
        reasons.append("CONTRACT_QUOTE_MULTIPLIER_IDENTITY_UNVERIFIED")
    return {"status": "BLOCKED" if reasons else "PASS", "checked_at": now.isoformat(),
            "reasons": reasons, "source_binding": deepcopy(accepted),
            "valid_until": min(common.timestamp(proof["valid_until"]) for proof in accepted.values()).isoformat()
                if not reasons else None}


def multiplier_matches(proof, row):
    value = proof.get("multiplier")
    return (proof.get("interface") == "US_OPTION_QUOTE"
            and proof.get("multiplier_field") == "contract_multiplier"
            and proof.get("contract_symbol") == row.get("contract_id")
            and proof.get("underlying") == row.get("underlying")
            and common.finite(value) and value > 0 and value == int(value)
            and common.finite(row.get("raw_multiplier")) and row["raw_multiplier"] == value
            and row.get("multiplier") == value and row.get("multiplier_status") == "VERIFIED_NATIVE_FIELD")


def normalize_minutes(rows, reference):
    """Use one reviewed scale for live and historical amounts, preserving raw data."""
    conversion = reference.get("unit_conversion") or {}
    volume = conversion.get("shares_per_raw_volume", 1)
    turnover = conversion.get("currency_units_per_raw_turnover", 1)
    if (not all(common.finite(value) and value > 0 for value in (volume, turnover))
            or (conversion and conversion.get("source_sha256") != reference.get("volume_unit_evidence_hash"))):
        raise ValueError("NATIVE_UNIT_CONVERSION_UNVERIFIED")
    return [{**row, "raw_volume": row["volume"], "raw_turnover": row["turnover"],
             "volume": row["volume"] * volume, "turnover": row["turnover"] * turnover,
             "unit_conversion": conversion} for row in rows], turnover


def build(quote, *, symbol, session, now, reviews=None, root=ROOT, prior_close_bar=None):
    reviews = reviews or {}
    units = source_review(reviews.get("candlestick_units", {}), root=root, now=now)
    unit_ok = bool(units and units.get("interface") == "US_EQUITY_CANDLESTICK_1M"
                   and units.get("volume_unit") == "SHARES" and units.get("turnover_currency") == "USD")
    volume_factor = units.get("shares_per_raw_volume", 1) if units else None
    turnover_factor = units.get("currency_units_per_raw_turnover", 1) if units else None
    unit_ok = unit_ok and all(common.finite(value) and value > 0 for value in (volume_factor, turnover_factor))
    basis_ok = False
    basis = prior_close_bar or {}
    try:
        previous_day = sessions_before(date.fromisoformat(session), 1)[0]
        end = session_bounds_utc(date.fromisoformat(previous_day))[1]
        basis_ok = (basis.get("symbol") == symbol and basis.get("session") == previous_day
                    and basis.get("adjustment") == "NoAdjust" and basis.get("currency") == "USD"
                    and basis.get("source") == "LONGBRIDGE_HISTORY_MIN_1"
                    and common.timestamp(basis["open_at"]) == end - timedelta(minutes=1)
                    and end <= common.timestamp(basis["received_at"]) <= now
                    and common.digest({k: v for k, v in basis.items() if k != "source_hash"}) == basis.get("source_hash")
                    and common.finite(basis.get("close")) and basis["close"] > 0
                    and Decimal(str(basis["close"])) == Decimal(str(quote.get("previous_close"))))
    except (KeyError, TypeError, ValueError, ArithmeticError):
        pass
    valid_quote = False
    time_status, provider_ahead_seconds = "UNAVAILABLE", None
    try:
        received = common.timestamp(quote["received_at"])
        provided = common.timestamp(quote["quote_time"])
        provider_ahead_seconds = (provided - received).total_seconds()
        time_status = "PROVIDER_TIME_AFTER_RECEIPT" if provided > received else "RECEIPT_AFTER_CHECK" if received > now else "ORDERED"
        valid_quote = (quote.get("symbol") == symbol and quote.get("provider_status") == "available"
                       and common.timestamp(quote["received_at"]).astimezone(common.NY).date().isoformat() == session
                       and common.timestamp(quote["quote_time"]).astimezone(common.NY).date().isoformat() == session
                       and common.timestamp(quote["quote_time"]) <= common.timestamp(quote["received_at"]) <= now
                       and common.finite(quote.get("previous_close")) and quote["previous_close"] > 0)
    except (KeyError, TypeError, ValueError):
        pass
    return {"symbol": symbol, "session": session,
            "previous_close": quote.get("previous_close") if valid_quote else None,
            "received_at": quote.get("received_at"), "source_hash": common.digest(quote),
            "raw_quote": quote, "volume_unit": "SHARES" if unit_ok else "UNKNOWN",
            "time_evidence": {"state": time_status, "provider_ahead_seconds": provider_ahead_seconds,
                              "quote_time": quote.get("quote_time"), "received_at": quote.get("received_at"),
                              "checked_at": now.isoformat()},
            "volume_unit_evidence_hash": units["source_sha256"] if unit_ok else None,
            "unit_conversion": {"shares_per_raw_volume": volume_factor,
                                "currency_units_per_raw_turnover": turnover_factor,
                                "source_sha256": units["source_sha256"],
                                "method": "REVIEWED_NATIVE_INTERFACE_FACT_V1"} if unit_ok else None,
            "price_comparable": basis_ok, "price_basis_evidence_hash": basis["source_hash"] if basis_ok else None,
            "price_basis_method": "UNADJUSTED_PRIOR_CLOSE_EXACT_MATCH_NOT_EVENT_CLEARANCE",
            "prior_close_evidence": basis,
            "reference_blockers": [reason for valid, reason in (
                (valid_quote, "CURRENT_SESSION_PREVIOUS_CLOSE_UNVERIFIED"),
                (unit_ok, "NATIVE_CANDLESTICK_UNIT_EVIDENCE_MISSING"),
                (basis_ok, "SESSION_PRICE_BASIS_EVIDENCE_MISSING")) if not valid]
                + (["REFERENCE_TIME_CONFLICT"] if time_status in {"PROVIDER_TIME_AFTER_RECEIPT", "RECEIPT_AFTER_CHECK"} else [])}
