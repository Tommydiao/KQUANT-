"""As-of event review for the two-hour research strategy.

Provider calendar observations are evidence, not proof that no issuer news exists.
Until a source matrix can be verified automatically, each applicable category
needs a named, source-bound review. This module never changes the legacy gate.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .option_calendar_source import canonical, source_observations
from .option_official_source import capture as capture_official_source, source_check as official_source_check
from .stock_store import connect
from .bounded_sqlite import read_connection

ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = ROOT / "config/options_event_coverage_v3_proposal.json"
APPROVAL = ROOT / "config/review_acceptances/options_event_coverage_o_setup_20260923.json"
POLICY_ID = "STRAT-SHORT-ATM-RANGE-EXPANSION-2H-V1"
CATEGORY_SOURCES = {
    "earnings": ("earnings",),
    "dividends": ("dividends",),
    "corporate": ("splits", "mergers", "meetings"),
    "macro": ("macro",),
}
ASSET_CLASSES = {"COMMON_STOCK", "ADR", "REIT", "ETF", "ETN", "FUND"}
NY = ZoneInfo("America/New_York")


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return result.astimezone(UTC)


def _approval(policy_hash: str, scope_hash: str, path: Path = APPROVAL,
              *, proposal_path: Path = PROPOSAL,
              event_policy_id: str = "EVENT-COVERAGE-V3-AUTOMATED-NORMAL-HUMAN-EXCEPTION") -> dict | None:
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
        digest = hashlib.sha256(proposal_path.read_bytes()).hexdigest()
        if (row.get("status") == "APPROVED" and row.get("approved_by") == "OWNER"
                and row.get("policy_id") == event_policy_id
                and row.get("policy_sha256") == digest
                and row.get("strategy_hash") == policy_hash
                and row.get("scope_hash") == scope_hash):
            return row
    except (OSError, ValueError, TypeError):
        pass
    return None


def _instrument(db_path: Path, symbol: str) -> dict | None:
    if symbol == "*":
        return {"symbol": "*", "identity_status": "verified", "provider_symbol": "US_MARKET"}
    try:
        with read_connection(db_path, seconds=.25) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("""SELECT normalized_symbol AS symbol,provider_symbol,identity_status,
                security_type FROM stock_watchlist_members WHERE normalized_symbol=? AND status='active'
                ORDER BY updated_at DESC LIMIT 1""", (symbol,)).fetchone()
            return dict(row) if row else None
    except (sqlite3.Error, TimeoutError):
        return None


@lru_cache(maxsize=48)
def _validated_semantic_hash(path: str, raw_hash: str, modified_ns: int) -> str:
    raw = Path(path).read_bytes()
    if hashlib.sha256(raw).hexdigest() != raw_hash:
        raise ValueError("SOURCE_ARCHIVE_HASH_MISMATCH")
    row = json.loads(raw)
    return hashlib.sha256(canonical({
        "category": row.get("category"), "query_start": row.get("query_start"),
        "query_end": row.get("query_end"), "pages_complete": row.get("pages_complete"),
        "issues": row.get("issues"),
        "events": sorted(row.get("matching_events", []), key=canonical),
    }).encode()).hexdigest()


def _source_state(db_path: Path, symbol: str, category: str, now: datetime,
                  *, horizon_end: datetime | None = None) -> dict:
    observation = source_observations(db_path, symbol, now=now)
    rows = observation.get("categories") or {}
    hashes, reasons, references = {}, [], []
    for name in CATEGORY_SOURCES[category]:
        row = rows.get(name)
        if not isinstance(row, dict):
            reasons.append(f"{name}:SOURCE_MISSING")
            continue
        if row.get("freshness") != "CURRENT":
            reasons.append(f"{name}:SOURCE_{row.get('freshness', 'UNKNOWN')}")
        if not row.get("pages_complete") or row.get("issues"):
            reasons.append(f"{name}:PAGES_OR_COUNTS_INCOMPLETE")
        digest = row.get("semantic_hash")
        if not isinstance(digest, str) or len(digest) != 64:
            reasons.append(f"{name}:CONTENT_HASH_MISSING")
        else:
            try:
                raw_hash = str(row.get("source_hash") or "")
                source_file = Path(db_path).parent / "option_event_sources" / f"{raw_hash}.json"
                if len(raw_hash) != 64 or any(c not in "0123456789abcdef" for c in raw_hash) or _validated_semantic_hash(
                        str(source_file), raw_hash, source_file.stat().st_mtime_ns) != digest:
                    raise ValueError("SOURCE_CONTENT_HASH_MISMATCH")
                hashes[name] = digest
            except (OSError, ValueError, TypeError):
                reasons.append(f"{name}:SOURCE_ARCHIVE_HASH_MISMATCH")
        try:
            start = datetime.fromisoformat(str(row.get("query_start"))).date()
            end = datetime.fromisoformat(str(row.get("query_end"))).date()
            day = now.astimezone(NY).date()
            if start > day or end < (horizon_end or now + timedelta(days=7)).astimezone(NY).date():
                reasons.append(f"{name}:SOURCE_WINDOW_INCOMPLETE")
        except ValueError:
            reasons.append(f"{name}:SOURCE_WINDOW_UNKNOWN")
        references.append({key: row.get(key) for key in (
            "source_url", "source_hash", "semantic_hash", "query_start", "query_end",
            "knowledge_as_of", "pages_complete", "issues", "freshness")})
    if observation.get("status") != "UNREVIEWED_SOURCE_OBSERVATIONS":
        reasons.append("SOURCE_ARCHIVE_UNAVAILABLE")
    return {"hashes": hashes, "reasons": reasons, "references": references,
            "scope_hash": observation.get("scope_hash")}


def _review_rows(db_path: Path, symbol: str) -> list[dict]:
    try:
        with read_connection(db_path, seconds=.25) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute("""SELECT * FROM option_event_coverage
                WHERE symbol IN (?, '*') ORDER BY recorded_at DESC, coverage_id LIMIT 256""", (symbol,))]
    except (sqlite3.Error, TimeoutError):
        return []


def import_v3_review(db_path: Path, payload: dict, *, reviewer: str,
                     policy_hash: str, scope_hash: str, now: datetime | None = None,
                     approval_path: Path = APPROVAL, proposal_path: Path = PROPOSAL,
                     event_policy_id: str = "EVENT-COVERAGE-V3-AUTOMATED-NORMAL-HUMAN-EXCEPTION",
                     minimum_horizon: datetime | None = None) -> str:
    """Append a human exception review bound to current provider and official evidence."""
    from .option_event_coverage import import_coverage, validate_events

    current = (now or datetime.now(UTC)).astimezone(UTC)
    approval = _approval(policy_hash, scope_hash, approval_path,
                         proposal_path=proposal_path, event_policy_id=event_policy_id)
    if approval is None:
        raise ValueError("V3_POLICY_OR_SCOPE_NOT_APPROVED")
    symbol = str(payload.get("symbol") or "").upper().removesuffix(".US")
    category = str(payload.get("category") or "")
    if category not in CATEGORY_SOURCES or (symbol == "*") != (category == "macro"):
        raise ValueError("REVIEW_CATEGORY_OR_ASSET_INVALID")
    instrument = _instrument(db_path, symbol)
    if not instrument or instrument.get("identity_status") != "verified" or (
            symbol != "*" and not str(instrument.get("provider_symbol") or "").endswith(".US")):
        raise ValueError("INSTRUMENT_IDENTITY_UNVERIFIED")
    asset_class = "US_MARKET" if symbol == "*" else str(payload.get("asset_class") or "")
    if asset_class != "US_MARKET" and asset_class not in ASSET_CLASSES:
        raise ValueError("ASSET_CLASS_REQUIRES_REVIEW")
    if not isinstance(reviewer, str) or not reviewer.strip() or reviewer == "local@kquant.local":
        raise ValueError("AUTHENTICATED_REVIEWER_REQUIRED")
    source = (_source_state(db_path, symbol, category, current)
              if minimum_horizon is None else _source_state(db_path, symbol, category, current,
                                                             horizon_end=minimum_horizon))
    if source["scope_hash"] != scope_hash or len(source["hashes"]) != len(CATEGORY_SOURCES[category]):
        raise ValueError("PROVIDER_SOURCE_OR_SCOPE_UNAVAILABLE")
    if any(not reason.endswith("PAGES_OR_COUNTS_INCOMPLETE") for reason in source["reasons"]):
        raise ValueError("PROVIDER_SOURCE_NOT_CURRENT_OR_VERIFIED")
    exception = str(payload.get("exception_reason") or "").strip()
    if source["reasons"] and len(exception) < 30:
        raise ValueError("INCOMPLETE_PROVIDER_SOURCE_NEEDS_EXPLICIT_EXCEPTION")
    url = str(payload.get("official_source_url") or "")
    content = str(payload.get("official_source_content") or "")
    if urlparse(url).scheme != "https" or len(content.strip()) < 40 or len(content) > 32768:
        raise ValueError("OFFICIAL_SOURCE_URL_AND_REVIEWED_CONTENT_REQUIRED")
    start = _time(str(payload.get("coverage_start")))
    end = _time(str(payload.get("coverage_end")))
    if start > current or end < (minimum_horizon or current + timedelta(days=7)):
        raise ValueError("ORIGINAL_EVENT_HORIZON_NOT_COVERED")
    from .market_clock import session_bounds_utc
    session_close = session_bounds_utc(current.astimezone(NY).date())[1]
    valid_until = min(session_close, _time(str(payload.get("valid_until"))))
    if valid_until <= current:
        raise ValueError("REVIEW_EXPIRED_OR_MARKET_CLOSED")
    if payload.get("risk_state") not in {"CLEAR", "KNOWN_BLOCKER"}:
        raise ValueError("EXPLICIT_EVENT_RISK_STATE_REQUIRED")
    events = payload.get("events")
    validate_events(events, coverage_start=start, coverage_end=end, risk_state=payload["risk_state"])
    official = capture_official_source(db_path, url, now=current)
    if official["status"] != "VERIFIED":
        raise ValueError("OFFICIAL_SOURCE_NOT_VERIFIED")
    reviewed = {
        "symbol": symbol, "category": category, "reviewer": reviewer.strip(),
        "source_url": url, "source_hash": official["content_hash"],
        "official_checked_at": official["checked_at"],
        "official_source_content": content, "coverage_start": start.isoformat(),
        "coverage_end": end.isoformat(), "available_at": current.isoformat(),
        "reviewed_at": current.isoformat(), "valid_until": valid_until.isoformat(),
        "review_status": "reviewed", "events": events,
        "no_events_confirmed": not events, "coverage_complete": True,
        "v3_policy_id": event_policy_id,
        "v3_policy_hash": approval["policy_sha256"],
        "strategy_hash": policy_hash, "scope_hash": scope_hash,
        "asset_class": asset_class, "applicable": payload.get("applicable") is not False,
        "risk_state": payload["risk_state"], "risk_summary": str(payload.get("risk_summary") or "")[:1000],
        "provider_semantic_hashes": source["hashes"], "provider_source_refs": source["references"],
        "exception_reason": exception, "review_method": "NAMED_HUMAN_SOURCE_EXCEPTION",
    }
    if not reviewed["applicable"] and not reviewed["risk_summary"]:
        raise ValueError("ASSET_CATEGORY_INAPPLICABILITY_NEEDS_REASON")
    if not reviewed["applicable"] and not (category == "earnings" and asset_class in {"ETF", "ETN", "FUND"}):
        raise ValueError("ASSET_CATEGORY_IS_APPLICABLE")
    return import_coverage(db_path, reviewed, now=current)


def v3_event_context(db_path: Path, symbol: str, as_of: str | None = None, *, until: str | None = None,
                     policy_hash: str, scope_hash: str, approval_path: Path = APPROVAL,
                     proposal_path: Path = PROPOSAL,
                     event_policy_id: str = "EVENT-COVERAGE-V3-AUTOMATED-NORMAL-HUMAN-EXCEPTION") -> dict:
    current = _time(as_of) if as_of else datetime.now(UTC)
    horizon = _time(until) if until else current + timedelta(days=7)
    normalized = symbol.upper().removesuffix(".US")
    approval = _approval(policy_hash, scope_hash, approval_path,
                         proposal_path=proposal_path, event_policy_id=event_policy_id)
    instrument = _instrument(db_path, normalized)
    reasons, missing, stale, blockers, selected, sources, states = {}, [], [], [], {}, {}, {}
    if not approval:
        reasons["policy"] = ["V3_POLICY_OR_SCOPE_NOT_APPROVED"]
    if not instrument or instrument.get("identity_status") != "verified" or not str(instrument.get("provider_symbol") or "").endswith(".US"):
        reasons["identity"] = ["INSTRUMENT_IDENTITY_UNVERIFIED"]
    rows = _review_rows(db_path, normalized)
    asset_classes = set()
    for category in CATEGORY_SOURCES:
        target = "*" if category == "macro" else normalized
        source = (_source_state(db_path, target, category, current)
                  if event_policy_id == "EVENT-COVERAGE-V3-AUTOMATED-NORMAL-HUMAN-EXCEPTION"
                  else _source_state(db_path, target, category, current, horizon_end=horizon))
        if source["scope_hash"] != scope_hash:
            source["reasons"].append("SOURCE_SCOPE_CHANGED")
        eligible = []
        for row in rows:
            if row["category"] != category or row["symbol"] != target:
                continue
            try:
                payload = json.loads(row["payload_json"])
                if (payload.get("v3_policy_hash") == approval["policy_sha256"] if approval else False) and (
                        payload.get("strategy_hash") == policy_hash and payload.get("scope_hash") == scope_hash
                        and _time(row["available_at"]) <= current and _time(row["reviewed_at"]) <= current
                        and _time(row["recorded_at"]) <= current):
                    eligible.append((row, payload))
            except (ValueError, KeyError, TypeError):
                continue
        if not eligible:
            missing.append(category)
            reasons[category] = ["NAMED_SOURCE_REVIEW_MISSING", *source["reasons"]]
            states[category] = {"trade_eligible": False, "reasons": reasons[category],
                                "review_method": "NAMED_HUMAN_SOURCE_EXCEPTION"}
            continue
        row, payload = eligible[0]
        category_reasons = list(source["reasons"])
        if _time(row["valid_until"]) <= current or _time(row["coverage_start"]) > current or _time(row["coverage_end"]) < horizon:
            category_reasons.append("REVIEW_OR_HORIZON_EXPIRED")
            stale.append(category)
        if payload.get("provider_semantic_hashes") != source["hashes"]:
            category_reasons.append("SOURCE_CONTENT_CHANGED")
        official = official_source_check(db_path, row["source_url"], now=current)
        if official.get("status") != "VERIFIED":
            category_reasons.append(f"OFFICIAL_SOURCE_{official.get('status', 'UNKNOWN')}")
        elif official.get("content_hash") != row["source_hash"]:
            category_reasons.append("OFFICIAL_SOURCE_CONTENT_CHANGED")
        # A named exception may account for pagination defects, never for stale or changed sources.
        if payload.get("exception_reason"):
            category_reasons = [reason for reason in category_reasons if not reason.endswith("PAGES_OR_COUNTS_INCOMPLETE")]
        if category_reasons:
            missing.append(category)
            reasons[category] = category_reasons
            if any("STALE" in reason for reason in category_reasons):
                stale.append(category)
        selected[category] = row["coverage_id"]
        sources[category] = {"source_url": row["source_url"], "source_hash": row["source_hash"],
                             "reviewed_at": row["reviewed_at"], "valid_until": row["valid_until"],
                             "provider_source_refs": payload.get("provider_source_refs", []),
                             "current_provider_source_refs": source["references"],
                             "reviewer": row["reviewer"], "asset_class": payload.get("asset_class"),
                             "official_checked_at": official.get("checked_at"),
                             "official_check_status": official.get("status")}
        if category != "macro":
            asset_classes.add(payload.get("asset_class"))
        for event in payload.get("events", []):
            if event.get("blocks_entry") and _time(event["end_at"]) >= current and _time(event["start_at"]) <= horizon:
                blockers.append({"category": category, **event, "coverage_id": row["coverage_id"]})
        if payload.get("risk_state") == "KNOWN_BLOCKER" and not any(item["category"] == category for item in blockers):
            missing.append(category)
            reasons[category] = ["BLOCKER_DISPOSITION_INCONSISTENT"]
        states[category] = {"trade_eligible": not reasons.get(category) and not any(item["category"] == category for item in blockers),
                            "reasons": reasons.get(category, []), "coverage_id": row["coverage_id"],
                            "sources": [sources[category]], "review_method": "NAMED_HUMAN_SOURCE_EXCEPTION"}
    if len(asset_classes) > 1 or any(asset not in ASSET_CLASSES for asset in asset_classes):
        reasons["identity"] = ["ASSET_CLASS_REVIEW_CONFLICT"]
    if missing:
        missing = list(dict.fromkeys(missing))
    eligible = bool(approval) and not reasons and not missing and not blockers and len(selected) == len(CATEGORY_SOURCES)
    return {"status": "STALE" if stale else "event_blocked" if blockers else "reviewed" if eligible else "incomplete",
            "policy_id": approval.get("policy_id") if approval else None, "as_of": current.isoformat(),
            "coverage_until": horizon.isoformat(), "trade_eligible": eligible,
            "missing_categories": missing, "blocking_events": blockers, "stale_categories": stale,
            "missing_reasons": reasons, "coverage_ids": selected, "sources": sources, "category_states": states,
            "coverage_quality": "COVERED_AS_OF" if eligible else "PARTIAL" if selected else "NOT_CHECKED",
            "known_risk_state": "KNOWN_BLOCKER" if blockers else "UNKNOWN" if not eligible else "CLEAR_UNDER_POLICY",
            "claim": "NO_KNOWN_BLOCKING_EVENT_IN_VERIFIED_SOURCES_AS_OF_KNOWLEDGE_TIME" if eligible else None,
            "option_only": True, "real_orders_enabled": False}
