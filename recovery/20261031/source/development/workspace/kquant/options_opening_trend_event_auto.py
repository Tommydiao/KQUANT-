"""Source-bound programmatic event checks; never manufacture human reviews."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import urlparse

from .option_calendar_source import canonical, source_observations
from .option_event_coverage_v3 import ASSET_CLASSES, CATEGORY_SOURCES, NY, _instrument, _time
from .option_official_source import source_check
from .options_opening_trend_event_parsers import PARSERS as EXTRA_PARSERS, parse as parse_schedule

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config/options_opening_trend_event_sources_v1.json"
PARSER = "ICS-TZ-AWARE-NONRECURRING-V1"
MAX_BYTES = 512 * 1024
REQUIREMENTS = {
    "earnings": ["issuer_earnings_calendar"],
    "dividends": ["issuer_or_fund_distribution_calendar"],
    "corporate": ["issuer_corporate_action_and_announcement_calendar"],
    "macro": ["bls_release_calendar", "bea_release_calendar", "fomc_calendar"],
}


def _hash(value):
    return sha256(canonical(value).encode()).hexdigest()


@lru_cache(maxsize=64)
def _read(path, modified, size):
    if size > MAX_BYTES:
        raise ValueError("SOURCE_TOO_LARGE")
    return Path(path).read_bytes()


def _bytes(path):
    stat = path.stat()
    return _read(str(path), stat.st_mtime_ns, stat.st_size)


def load_registry(path=REGISTRY):
    raw = _bytes(Path(path))
    row = json.loads(raw)
    if (not isinstance(row, dict) or row.get("parser") != PARSER
            or row.get("max_age_seconds") != 900
            or row.get("requirements") != REQUIREMENTS
            or row.get("not_applicable") != {"earnings": ["ETF", "ETN", "FUND"]}
            or not isinstance(row.get("source_bindings"), list)
            or not isinstance(row.get("asset_bindings"), list)):
        raise ValueError("AUTO_SOURCE_CONTRACT_INVALID")
    return {**row, "sha256": sha256(raw).hexdigest()}


def _fact(binding, *, now, root, authority):
    """A named, immutable authority review proves a fact, not current freshness."""
    proof = binding.get("proof") or {}
    try:
        url = urlparse(proof["source_url"])
        path = (root / proof["source_path"]).resolve()
        if (proof.get("status") != "APPROVED" or not proof.get("reviewer")
                or proof["reviewer"] in {"OWNER", "local@kquant.local", "AUTOMATED"}
                or not _time(proof["reviewed_at"]) <= now < _time(proof["valid_until"])
                or not authority or url.scheme != "https" or not url.hostname or url.hostname != authority
                or url.username or url.password or url.port not in (None, 443)
                or not path.is_relative_to(root.resolve())):
            return False
        raw = _bytes(path)
        excerpt = proof.get("excerpt")
        return (sha256(raw).hexdigest() == proof["source_sha256"]
                and isinstance(excerpt, str) and len(excerpt.strip()) >= 20
                and excerpt in raw.decode("utf-8"))
    except (KeyError, TypeError, ValueError, OSError, UnicodeError):
        return False


def asset_class(instrument, registry, *, now, root):
    if (not instrument or instrument.get("identity_status") != "verified"
            or not str(instrument.get("provider_symbol") or "").endswith(".US")):
        return None, "INSTRUMENT_IDENTITY_UNVERIFIED"
    rows = [r for r in registry["asset_bindings"] if isinstance(r, dict)
            and r.get("symbol") == instrument["symbol"]
            and r.get("provider_symbol") == instrument["provider_symbol"]
            and r.get("asset_class") in ASSET_CLASSES
            and _fact(r, now=now, root=root, authority=r.get("authority_domain"))]
    if len(rows) != 1:
        return None, "ASSET_CLASS_EVIDENCE_MISSING_OR_CONFLICTING"
    return rows[0]["asset_class"], None


def parse_ics(raw):
    """Use RFC5545 parsing; floating dates and recurrence are not guessed."""
    from icalendar import Calendar
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("SOURCE_EMPTY_OR_TOO_LARGE")
    calendar = Calendar.from_ical(raw)
    if calendar.name != "VCALENDAR" or calendar.get("VERSION") != "2.0":
        raise ValueError("CALENDAR_SCHEMA_INVALID")
    events, issues, seen = [], [], {}
    components = calendar.walk("VEVENT")
    if len(components) > 2000:
        raise ValueError("CALENDAR_EVENT_LIMIT")
    for component in components:
        try:
            uid = str(component.get("UID") or "")
            if not uid or component.errors:
                raise ValueError("EVENT_ID_OR_PARSE_ERROR")
            if component.get("STATUS") == "CANCELLED":
                continue
            if component.errors or any(component.get(k) is not None for k in ("RRULE", "RDATE", "EXDATE", "RECURRENCE-ID")):
                raise ValueError("EVENT_RECURRENCE_OR_PARSE_ERROR")
            name = str(component.get("SUMMARY") or "")
            start = component.decoded("DTSTART")
            if not uid or not name.strip() or not isinstance(start, datetime) or start.tzinfo is None:
                raise ValueError("EVENT_ID_OR_EXPLICIT_TIME_MISSING")
            end = component.decoded("DTEND") if component.get("DTEND") is not None else start
            if component.get("DURATION") is not None:
                if component.get("DTEND") is not None:
                    raise ValueError("EVENT_END_CONFLICT")
                end = start + component.decoded("DURATION")
            if not isinstance(end, datetime) or end.tzinfo is None or end < start:
                raise ValueError("EVENT_END_INVALID")
            row = {"id": uid, "name": name, "start_at": start.astimezone(UTC).isoformat(),
                   "end_at": end.astimezone(UTC).isoformat(), "raw_component_sha256": sha256(component.to_ical()).hexdigest()}
            if uid in seen and seen[uid] != row:
                raise ValueError("EVENT_ID_CONFLICT")
            seen[uid] = row
        except (KeyError, ValueError, TypeError, OverflowError) as exc:
            issues.append(str(exc) if isinstance(exc, ValueError) else "EVENT_PARSE_FAILED")
    events.extend(seen.values())
    return {"parser": PARSER, "events": events, "issues": sorted(set(issues))}


def _provider(db, symbol, category, *, now, horizon, scope_hash):
    observed = source_observations(db, symbol, now=now)
    reasons, refs, events = [], [], []
    if observed.get("scope_hash") != scope_hash:
        reasons.append("PROVIDER_SCOPE_CHANGED_OR_MISSING")
    for name in CATEGORY_SOURCES[category]:
        entry = (observed.get("categories") or {}).get(name)
        if not isinstance(entry, dict):
            reasons.append(name + ":SOURCE_MISSING")
            continue
        refs.append({"category": name, **entry})
        if entry.get("freshness") != "CURRENT":
            reasons.append(name + ":SOURCE_" + str(entry.get("freshness", "UNKNOWN")))
        if not entry.get("pages_complete") or entry.get("issues"):
            reasons.append(name + ":PAGES_OR_COUNTS_INCOMPLETE")
        try:
            digest = entry["source_hash"]
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError("SOURCE_HASH_INVALID")
            raw = _bytes(Path(db).parent / "option_event_sources" / (digest + ".json"))
            if sha256(raw).hexdigest() != digest:
                raise ValueError("SOURCE_ARCHIVE_HASH_MISMATCH")
            payload = json.loads(raw)
            if any(entry.get(key) != payload.get(key) for key in
                   ("knowledge_as_of", "query_start", "query_end", "pages_complete", "issues")):
                raise ValueError("SOURCE_INDEX_CONTENT_MISMATCH")
            if (_hash({"category": name, "query_start": payload.get("query_start"),
                       "query_end": payload.get("query_end"), "pages_complete": payload.get("pages_complete"),
                       "issues": payload.get("issues"), "events": sorted(payload.get("matching_events", []), key=canonical)})
                    != entry.get("semantic_hash")):
                raise ValueError("SOURCE_CONTENT_HASH_MISMATCH")
            if (datetime.fromisoformat(payload["query_start"]).date() > now.astimezone(NY).date()
                    or datetime.fromisoformat(payload["query_end"]).date() < horizon.astimezone(NY).date()):
                raise ValueError("SOURCE_WINDOW_INCOMPLETE")
            # Inspect raw groups, including entries the watchlist filter could not identify.
            for page in payload.get("pages", []):
                for group in page["raw"]["groups"]:
                    for item in group["events"]:
                        if item.get("market") != "US":
                            reasons.append(name + ":EVENT_MARKET_UNKNOWN_OR_CONFLICTING")
                            continue
                        target = str(item.get("symbol") or "").upper().removesuffix(".US")
                        if category != "macro" and not target:
                            reasons.append(name + ":EVENT_ASSET_UNRESOLVED")
                            continue
                        if category != "macro" and target != symbol:
                            continue
                        try:
                            at = _time(str(item.get("datetime")))
                        except (ValueError, TypeError, OverflowError):
                            reasons.append(name + ":EVENT_TIME_BASIS_UNVERIFIED")
                            events.append({"category": category, "name": item.get("content") or name,
                                           "raw_datetime": item.get("datetime"), "source_hash": digest,
                                           "disposition": "REQUIRES_REVIEW"})
                            continue
                        if now <= at <= horizon:
                            events.append({"category": category, "name": item.get("content") or name,
                                           "start_at": at.isoformat(), "end_at": at.isoformat(),
                                           "source_hash": digest, "disposition": "REQUIRES_REVIEW"})
        except (KeyError, TypeError, ValueError, OSError, UnicodeError):
            reasons.append(name + ":SOURCE_ARCHIVE_OR_WINDOW_UNVERIFIED")
    return {"reasons": sorted(set(reasons)), "sources": refs, "events": events}


def _official(db, binding, *, now, horizon, root):
    source_url = binding.get("source_url")
    result = {"source_url": source_url, "source_id": binding.get("source_id"), "events": [], "reasons": []}
    try:
        url = urlparse(source_url)
        if (url.scheme != "https" or url.username or url.password or url.port not in (None, 443)
                or url.hostname != binding.get("authority_domain")
                or binding.get("parser") not in {PARSER, *EXTRA_PARSERS}
                or not _fact(binding, now=now, root=root, authority=url.hostname)):
            raise ValueError("OFFICIAL_AUTHORITY_OR_COVERAGE_PROOF_MISSING")
        if (_time(binding["coverage_start"]) > now or _time(binding["coverage_end"]) < horizon
                or binding.get("scope_of_claim") != "COMPLETE_PUBLISHED_SCHEDULE_AS_OF"):
            raise ValueError("OFFICIAL_COVERAGE_WINDOW_UNVERIFIED")
        check = source_check(db, source_url, now=now)
        result.update(check)
        if check.get("status") != "VERIFIED":
            raise ValueError("OFFICIAL_SOURCE_" + str(check.get("status", "UNKNOWN")))
        digest = check["content_hash"]
        raw = _bytes(Path(db).parent / "option_event_sources/official" / (digest + ".bin"))
        if sha256(raw).hexdigest() != digest:
            raise ValueError("OFFICIAL_ARCHIVE_HASH_MISMATCH")
        parsed = parse_ics(raw) if binding["parser"] == PARSER else parse_schedule(raw, binding)
        result["parser"] = parsed["parser"]
        result["reasons"].extend(parsed["issues"])
        disposition = binding.get("event_disposition", "REQUIRES_REVIEW")
        if disposition not in {"KNOWN_BLOCKER", "REQUIRES_REVIEW"}:
            raise ValueError("EVENT_DISPOSITION_UNVERIFIED")
        result["events"] = [{**event, "source_url": source_url, "source_hash": digest,
                              "disposition": disposition} for event in parsed["events"]
                             if _time(event["end_at"]) >= now and _time(event["start_at"]) <= horizon]
    except (KeyError, TypeError, ValueError, OSError, UnicodeError) as exc:
        result["reasons"].append(str(exc) if isinstance(exc, ValueError) else "OFFICIAL_SOURCE_UNAVAILABLE")
    return result


def automatic_context(db, symbol, *, now, horizon, policy_hash, scope_hash, approval=None,
                      registry=None, root=ROOT, instrument=None):
    now, horizon = _time(now.isoformat()), _time(horizon.isoformat())
    symbol = symbol.upper().removesuffix(".US")
    try:
        registry = registry or load_registry()
        asset, identity_reason = asset_class(instrument or _instrument(db, symbol), registry, now=now, root=root)
    except (OSError, TypeError, KeyError, ValueError):
        return {"status": "UNAVAILABLE", "trade_eligible": False, "known_risk_state": "UNKNOWN",
                "missing_reasons": {"automatic": ["AUTO_SOURCE_CONTRACT_UNAVAILABLE"]}, "category_states": {}}
    accepted = bool(approval and approval.get("status") == "APPROVED"
                    and approval.get("approved_by") == "OWNER"
                    and approval.get("strategy_hash") == policy_hash and approval.get("scope_hash") == scope_hash
                    and approval.get("automatic_source_contract_sha256") == registry["sha256"])
    reasons = {} if accepted else {"policy": ["AUTOMATIC_SOURCE_CONTRACT_NOT_ACCEPTED"]}
    if identity_reason:
        reasons["identity"] = [identity_reason]
    states, blockers, unresolved, valid_until = {}, [], [], []
    for category, required in registry["requirements"].items():
        provider = _provider(db, symbol, category, now=now, horizon=horizon, scope_hash=scope_hash)
        category_reasons = list(provider["reasons"])
        category_events = list(provider["events"])
        sources = list(provider["sources"])
        not_applicable = asset in registry.get("not_applicable", {}).get(category, [])
        if not_applicable:
            category_reasons, category_events, sources = [], [], []
        else:
            for source in sources:
                if source.get("knowledge_as_of"):
                    try:
                        valid_until.append(_time(source["knowledge_as_of"]) + timedelta(seconds=900))
                    except (TypeError, ValueError):
                        pass
            for source_id in required:
                bindings = [r for r in registry["source_bindings"] if isinstance(r, dict)
                            and r.get("source_id") == source_id and r.get("category") == category
                            and r.get("symbol") == ("*" if category == "macro" else symbol)]
                if len(bindings) != 1:
                    category_reasons.append(source_id + ":OFFICIAL_SOURCE_BINDING_MISSING_OR_CONFLICTING")
                    continue
                official = _official(db, bindings[0], now=now, horizon=horizon, root=root)
                sources.append(official)
                category_reasons.extend(source_id + ":" + r for r in official["reasons"])
                category_events.extend({"category": category, **r} for r in official["events"])
                if official.get("checked_at"):
                    valid_until.append(_time(official["checked_at"]) + timedelta(seconds=900))
                if not official["reasons"]:
                    valid_until.extend([_time(bindings[0]["proof"]["valid_until"]),
                                        _time(bindings[0]["coverage_end"])])
        category_blockers = [r for r in category_events if r.get("disposition") == "KNOWN_BLOCKER"]
        category_unresolved = [r for r in category_events if r.get("disposition") != "KNOWN_BLOCKER"]
        blockers.extend(category_blockers)
        unresolved.extend(category_unresolved)
        if category_unresolved:
            category_reasons.append("IMPORTANT_EVENT_REQUIRES_REVIEW")
        eligible = accepted and asset is not None and not category_reasons and not category_events
        states[category] = {"trade_eligible": eligible, "applicability": "NOT_APPLICABLE_UNDER_POLICY" if not_applicable else "APPLICABLE" if asset else "UNKNOWN",
                            "known_risk_state": "KNOWN_BLOCKER" if category_blockers else "UNRESOLVED" if category_unresolved else "CLEAR_UNDER_POLICY" if eligible else "UNKNOWN",
                            "reasons": sorted(set(category_reasons)), "sources": sources,
                            "events": category_events, "review_method": "AUTOMATED_SOURCE_VALIDATION"}
        if category_reasons:
            reasons[category] = sorted(set(category_reasons))
    if asset is not None:
        valid_until.extend(_time(row["proof"]["valid_until"]) for row in registry["asset_bindings"]
                           if isinstance(row, dict) and row.get("symbol") == symbol
                           and _fact(row, now=now, root=root, authority=row.get("authority_domain")))
    eligible = not reasons and not blockers and all(r["trade_eligible"] for r in states.values())
    result = {"status": "event_blocked" if blockers else "reviewed" if eligible else "incomplete",
              "as_of": now.isoformat(), "coverage_until": horizon.isoformat(), "policy_hash": policy_hash,
              "scope_hash": scope_hash, "source_contract_sha256": registry["sha256"], "asset_class": asset,
              "trade_eligible": eligible, "category_states": states, "missing_reasons": reasons,
              "blocking_events": blockers, "unresolved_events": unresolved,
              "known_risk_state": "KNOWN_BLOCKER" if blockers else "CLEAR_UNDER_POLICY" if eligible else "UNKNOWN",
              "review_method": "AUTOMATED_SOURCE_VALIDATION", "human_review_writes": 0,
              "claim": "NO_KNOWN_BLOCKING_EVENT_IN_VERIFIED_SOURCES_AS_OF_KNOWLEDGE_TIME" if eligible else None,
              "valid_until": min(valid_until).isoformat() if valid_until else None}
    result["evidence_id"] = _hash(result)
    return result


def combined_context(manual, automatic):
    """Combine categories; a current known risk never loses to another CLEAR path."""
    blockers = [*manual.get("blocking_events", []), *automatic.get("blocking_events", [])]
    states, reasons, sources, expiries = {}, {}, {}, []
    as_of = automatic.get("as_of") or manual.get("as_of")
    for category in CATEGORY_SOURCES:
        auto = (automatic.get("category_states") or {}).get(category, {})
        human = (manual.get("category_states") or {}).get(category, {})
        selected = auto if auto.get("trade_eligible") else human
        states[category] = deepcopy(selected)
        if "BLOCKER_DISPOSITION_INCONSISTENT" in human.get("reasons", []):
            reasons[category] = ["BLOCKER_DISPOSITION_INCONSISTENT"]
            states[category].update(trade_eligible=False, known_risk_state="UNKNOWN", reasons=reasons[category])
            continue
        if not selected.get("trade_eligible"):
            reasons[category] = list(dict.fromkeys([*auto.get("reasons", []), *human.get("reasons", [])])) or ["SOURCE_CHECK_OR_NAMED_REVIEW_MISSING"]
            continue
        source = ({"valid_until": automatic.get("valid_until"),
                   "review_method": "AUTOMATED_SOURCE_VALIDATION",
                   "source_refs": deepcopy(auto.get("sources", [])), "evidence_id": automatic.get("evidence_id")}
                  if selected is auto else deepcopy((manual.get("sources") or {}).get(category, {})))
        try:
            if selected is not auto:
                for event in auto.get("events", []):
                    if event.get("disposition") == "KNOWN_BLOCKER":
                        continue
                    digest = event.get("source_hash")
                    if event.get("source_url"):
                        reviewed = (event["source_url"] == source.get("source_url")
                                    and digest == source.get("source_hash"))
                    else:
                        reviewed = any(digest == ref.get("source_hash") for ref in
                            source.get("current_provider_source_refs", source.get("provider_source_refs", [])))
                    if not digest or not reviewed or selected.get("review_method") != "NAMED_HUMAN_SOURCE_EXCEPTION":
                        raise ValueError("IMPORTANT_EVENT_NOT_BOUND_TO_NAMED_REVIEW")
            current, end = _time(as_of), _time(source["valid_until"])
            if selected is not auto:
                checked = _time(source["official_checked_at"])
                if checked > current:
                    raise ValueError("FUTURE_SOURCE_CHECK")
                end = min(end, checked + timedelta(seconds=900))
                for reference in source.get("current_provider_source_refs", source.get("provider_source_refs", [])):
                    known = _time(reference["knowledge_as_of"])
                    if known > current:
                        raise ValueError("FUTURE_PROVIDER_SOURCE")
                    end = min(end, known + timedelta(seconds=900))
            if end <= current:
                raise ValueError("SOURCE_EXPIRED")
            if selected is not auto:
                source["review_valid_until"] = source["valid_until"]
            source.update(valid_until=end.isoformat(), review_method=selected.get("review_method"))
            sources[category] = source
            expiries.append(end)
            states[category]["valid_until"] = end.isoformat()
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            reason = ("IMPORTANT_EVENT_NOT_BOUND_TO_NAMED_REVIEW" if isinstance(exc, ValueError)
                      and str(exc) == "IMPORTANT_EVENT_NOT_BOUND_TO_NAMED_REVIEW"
                      else "SOURCE_VALIDITY_EXPIRED_OR_UNVERIFIED")
            reasons.setdefault(category, []).append(reason)
            states[category].update(trade_eligible=False, known_risk_state="UNKNOWN", reasons=reasons[category])
    for key in ("policy", "identity"):
        if (manual.get("missing_reasons") or {}).get(key):
            reasons[key] = manual["missing_reasons"][key]
    eligible = not blockers and not reasons and all(row.get("trade_eligible") for row in states.values())
    return {**manual, "as_of": as_of, "status": "event_blocked" if blockers else "reviewed" if eligible else "incomplete",
            "trade_eligible": eligible, "category_states": states, "missing_reasons": reasons,
            "sources": sources, "valid_until": min(expiries).isoformat() if expiries else None,
            "known_risk_state": "KNOWN_BLOCKER" if blockers else "CLEAR_UNDER_POLICY" if eligible else "UNKNOWN",
            "blocking_events": blockers, "automatic_coverage": automatic, "human_coverage": manual,
            "missing_categories": [key for key in reasons if key in CATEGORY_SOURCES],
            "coverage_quality": "COVERED_AS_OF" if eligible else "PARTIAL",
            "claim": "NO_KNOWN_BLOCKING_EVENT_IN_VERIFIED_SOURCES_AS_OF_KNOWLEDGE_TIME" if eligible else None}


def refresh_bound_sources(db, *, now, cancelled=lambda: False, limit=12):
    """Only previously proven public bindings, shared by every symbol and direction."""
    from .option_official_source import capture
    registry = load_registry()
    urls = set()
    for row in registry["source_bindings"]:
        if (isinstance(row, dict) and row.get("parser") in {PARSER, *EXTRA_PARSERS}
                and urlparse(str(row.get("source_url") or "")).scheme == "https"
                and urlparse(str(row.get("source_url") or "")).hostname == row.get("authority_domain")
                and _fact(row, now=now, root=ROOT, authority=row.get("authority_domain"))):
            urls.add(row["source_url"])
    ordered = sorted(urls, key=lambda url: (source_check(db, url, now=now).get("checked_at") or "", url))
    results = []
    for url in ordered[:max(0, min(limit, 12))]:
        if cancelled():
            break
        results.append(capture(db, url, now=datetime.now(UTC)))
    return {"source_contract_sha256": registry["sha256"], "checked": len(results),
            "remaining": len(urls) - len(results), "unconfigured": not urls,
            "verified_transport_only": sum(row["status"] == "VERIFIED" for row in results),
            "failed": sum(row["status"] != "VERIFIED" for row in results), "trade_eligible": False}
