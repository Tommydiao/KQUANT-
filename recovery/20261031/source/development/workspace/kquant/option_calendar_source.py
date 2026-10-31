"""Archive Longbridge financial calendar observations, never infer clearance."""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any
from pathlib import Path
from functools import lru_cache
from zoneinfo import ZoneInfo
from urllib.parse import urlencode

CATEGORY_NAMES = {"earnings": "Report", "dividends": "Dividend", "splits": "Split", "macro": "MacroData", "mergers": "Merge", "meetings": "Meeting"}
MAX_CALENDAR_REQUESTS_PER_RUN = 12
EVENT_FIELDS = ("id", "symbol", "market", "counter_name", "event_type", "activity_type",
                "date", "datetime", "content", "star", "currency", "date_type", "financial_market_time")


class CalendarBudgetDeferred(RuntimeError):
    pass


class CalendarSourceInFlight(RuntimeError):
    pass


def calendar_capabilities() -> dict:
    try:
        import longbridge.openapi as sdk
        context = getattr(sdk, 'CalendarContext', None)
        available = callable(getattr(context, 'finance_calendar', None))
    except ImportError:
        available = False
    return {'platform': 'Longbridge', 'context': 'CalendarContext', 'method': 'finance_calendar',
            'sdk_method_available': available, 'data_completeness_verified': False,
            'raw_observation_does_not_clear_entry': True}


def field(value: Any, key: str, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def calendar_request_path(category: str, start: date, end: date) -> str:
    if category not in CATEGORY_NAMES or not 0 <= (end - start).days <= 7:
        raise ValueError("INVALID_CALENDAR_REQUEST")
    # Same endpoint and query contract as the official CalendarContext implementation.
    return "/v1/quote/finance_calendar?" + urlencode({
        "date": start.isoformat(), "date_end": end.isoformat(),
        "types[]": CATEGORY_NAMES[category].lower(), "markets[]": "US"})


def calendar_snapshot(response: Any, *, category: str, start: date, end: date,
                      requested_at: datetime, received_at: datetime, symbols: tuple[str, ...]) -> dict:
    if category not in CATEGORY_NAMES or not 0 <= (end - start).days <= 7:
        raise ValueError("Use a registered category and at most eight calendar dates.")
    if requested_at.tzinfo is None or received_at.tzinfo is None or received_at < requested_at:
        raise ValueError("Request and receipt need ordered timezone-aware timestamps.")
    groups, issues, seen = [], [], set()
    original_response = response
    if isinstance(response, dict) and "code" in response:
        if type(response["code"]) is not int or response["code"] != 0 or not isinstance(response.get("data"), dict):
            issues.append("provider_response_failed_or_unknown")
            response = {}
        else:
            response = response["data"]
    raw_groups = field(response, "list")
    if not isinstance(raw_groups, (list, tuple)):
        issues.append("missing_date_groups")
        raw_groups = []
    for group in raw_groups:
        day = str(field(group, "date", ""))
        try:
            if not start <= date.fromisoformat(day) <= end:
                issues.append("out_of_range_date")
        except ValueError:
            issues.append("invalid_date")
        if day in seen:
            issues.append("duplicate_date_group")
        seen.add(day)
        infos = field(group, "infos")
        if not isinstance(infos, (list, tuple)):
            infos = []
            issues.append("missing_event_list")
        events = []
        for info in infos:
            if info is None or isinstance(info, (str, int, float, bool, list, tuple)):
                issues.append("event_schema_invalid")
            item = {name: field(info, name) for name in EVENT_FIELDS}
            pairs = field(info, "data_kv", []) or []
            if not isinstance(pairs, (list, tuple)):
                issues.append("event_data_kv_invalid")
                pairs = []
            item["data_kv"] = [{name: field(kv, name) for name in ("key", "value", "value_type", "value_raw")}
                               for kv in pairs]
            events.append(item)
        declared = field(group, "count")
        if type(declared) is not int or declared < 0 or declared != len(events):
            issues.append("count_mismatch_or_unknown")
        groups.append({"date": day, "declared_count": declared, "events": events})
    raw = {"response_date": field(response, "date"), "next_date": field(response, "next_date"), "groups": groups}
    if isinstance(original_response, dict):
        raw["provider_response"] = original_response
    digest = hashlib.sha256(canonical(raw).encode()).hexdigest()
    matching = [event for group in groups for event in group["events"]
                if category == "macro" or str(event.get("symbol") or "").removesuffix(".US") in symbols]
    return {"source": "Longbridge CalendarContext.finance_calendar", "source_hash": digest,
            "category": category, "requested_start": start.isoformat(), "requested_end": end.isoformat(),
            "request_started_at": requested_at.astimezone(UTC).isoformat(),
            "received_at": received_at.astimezone(UTC).isoformat(),
            "available_at": received_at.astimezone(UTC).isoformat(), "published_at": None,
            "raw": raw, "matching_events": matching, "issues": sorted(set(issues)),
            "response_status": "partial" if issues else "observed", "review_status": "pending_review",
            "coverage_complete": False, "trade_eligible": False,
            "limitations": ["Empty results do not prove absence of events.",
                            "Provider calendar timestamps are not quote event timestamps.",
                            "A split calendar does not cover every corporate announcement.",
                            "Publication time and per-symbol completeness are not established."]}


def collect_pages(fetch, *, category, start, end, symbols, max_pages=8, deadline_seconds=40, cancelled=lambda: False):
    """Bounded cursor walk; a complete transport walk is not reviewed risk clearance."""
    pages, issues, cursor, seen = [], [], start, set()
    deadline = time.monotonic() + deadline_seconds
    complete = False
    for _ in range(max_pages):
        if cancelled() or time.monotonic() >= deadline:
            issues.append("CANCELLED_OR_DEADLINE")
            break
        requested = datetime.now(UTC)
        try:
            response = fetch(category, cursor, end)
            page = calendar_snapshot(response, category=category, start=cursor, end=end,
                requested_at=requested, received_at=datetime.now(UTC), symbols=symbols)
        except CalendarSourceInFlight:
            issues.append("SOURCE_REQUEST_STILL_IN_FLIGHT")
            break
        except CalendarBudgetDeferred:
            issues.append("LOCAL_CALENDAR_REQUEST_CAP")
            break
        except Exception as exc:
            issues.append("PAGE_FAILED:" + type(exc).__name__)
            break
        pages.append(page)
        issues.extend(page["issues"])
        if time.monotonic() >= deadline:
            issues.append("PROVIDER_RESPONSE_AFTER_DEADLINE")
            break
        nxt = page["raw"]["next_date"]
        if nxt is None:
            issues.append("PAGINATION_METADATA_MISSING")
            break
        if nxt == "":
            complete = True
            break
        try:
            if not isinstance(nxt, str):
                raise ValueError("CURSOR_TYPE_UNKNOWN")
            new_cursor = date.fromisoformat(nxt)
        except ValueError:
            issues.append("INVALID_CURSOR")
            break
        if new_cursor <= cursor or nxt in seen:
            issues.append("CURSOR_NO_PROGRESS")
            break
        if new_cursor > end:
            complete = True
            break
        seen.add(nxt)
        cursor = new_cursor
    else:
        issues.append("PAGE_LIMIT")
    matched = {}
    for page in pages:
        for item in page["matching_events"]:
            # Source ID alone can be reused on event revisions; retain changed content.
            matched[hashlib.sha256(canonical(item).encode()).hexdigest()] = item
    return {"category": category, "market": "US", "query_start": start.isoformat(), "query_end": end.isoformat(),
            "knowledge_as_of": datetime.now(UTC).isoformat(), "source_url": "https://longbridge.github.io/openapi/python/reference_all/#calendarcontext",
            "pages": pages, "pages_complete": complete and not issues, "issues": sorted(set(issues)), "matching_events": list(matched.values()),
            "coverage_quality": "COVERED_AS_OF" if complete and not issues else "PARTIAL" if pages else "SOURCE_FAILED",
            "known_risk_state": "UNKNOWN", "review_method": "UNREVIEWED_PROVIDER_CALENDAR", "trade_eligible": False,
            "scope_of_claim": "KNOWN_CALENDAR_ENTRIES_ONLY_NOT_ALL_FUTURE_CORPORATE_NEWS", "published_at": None}


def publish_observations(source: Path, store: Path):
    """Content-addressed raw archive, not an entry-clearance import or a ledger."""
    store.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    index = {"scope_hash": manifest["scope_hash"], "manifest_count": manifest["manifest_count"], "categories": {},
             "ingested_at": datetime.now(UTC).isoformat(), "trade_eligible": False}
    for category in manifest["categories"]:
        raw = (source / f"{category}.json").read_bytes()
        identity = hashlib.sha256(raw).hexdigest()
        declared_hash = manifest["categories"][category]["file_sha256"]
        normalized_hash = hashlib.sha256(raw.decode("utf-8").replace("\r\n", "\n").encode()).hexdigest()
        if declared_hash not in {identity, normalized_hash}:
            raise ValueError("SOURCE_HASH_MISMATCH")
        target = store / f"{identity}.json"
        if not target.exists():
            target.write_bytes(raw)
        row = json.loads(raw)
        semantic_hash = hashlib.sha256(canonical({
            "category": category,
            "query_start": row.get("query_start"),
            "query_end": row.get("query_end"),
            "pages_complete": row.get("pages_complete"),
            "issues": row.get("issues"),
            "events": sorted(row.get("matching_events", []), key=canonical),
        }).encode()).hexdigest()
        index["categories"][category] = {key: row.get(key) for key in
            ("query_start", "query_end", "knowledge_as_of", "pages_complete", "coverage_quality", "known_risk_state", "issues", "source_url", "scope_of_claim")}
        index["categories"][category].update(source_hash=identity, raw_ref=target.name,
            semantic_hash=semantic_hash,
            manifest_hash=declared_hash, manifest_hash_basis="RAW_BYTES" if declared_hash == identity else "LEGACY_LF_NORMALIZED_UTF8",
            matching_symbols=sorted({str(item.get("symbol") or "").removesuffix(".US") for item in row.get("matching_events", [])}),
            event_count=len(row.get("matching_events", [])))
    encoded = canonical(index)
    (store / (hashlib.sha256(encoded.encode()).hexdigest() + ".index.json")).write_text(encoded, encoding="utf-8")
    temp = store / "current.tmp"
    temp.write_text(encoded, encoding="utf-8")
    temp.replace(store / "current.json")
    return index


@lru_cache(maxsize=4)
def _observations(path, modified):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def source_observations(db_path: Path, symbol: str, *, now: datetime | None = None):
    index = Path(db_path).parent / "option_event_sources/current.json"
    if not index.exists():
        return {"status": "NOT_CHECKED", "trade_eligible": False}
    try:
        data = _observations(str(index), index.stat().st_mtime_ns)
        current = (now or datetime.now(UTC)).astimezone(UTC)
        categories = {}
        for category, value in data["categories"].items():
            row = dict(value)
            try:
                observed = datetime.fromisoformat(str(row["knowledge_as_of"]))
                if observed.tzinfo is None:
                    raise ValueError("SOURCE_TIMEZONE_REQUIRED")
                observed = observed.astimezone(UTC)
                age = (current - observed).total_seconds()
                row["age_seconds"] = round(age, 3)
                row["freshness"] = "TIME_CONFLICT" if age < 0 else "STALE" if age > 900 else "CURRENT"
            except (TypeError, ValueError, KeyError):
                row["age_seconds"] = None
                row["freshness"] = "UNKNOWN"
            categories[category] = row
        return {"status": "UNREVIEWED_SOURCE_OBSERVATIONS", "categories": categories,
                "scope_hash": data["scope_hash"], "symbol": symbol, "trade_eligible": False,
                "ingested_at": data.get("ingested_at"), "max_age_seconds": 900,
                "applicability": "REQUIRES_VERIFIED_ASSET_TYPE_AND_APPROVED_CATEGORY_MATRIX",
                "corporate": "SPLITS_MERGERS_MEETINGS_DO_NOT_PROVE_ABSENCE_OF_OTHER_ANNOUNCEMENTS"}
    except (OSError, ValueError, KeyError):
        return {"status": "SOURCE_ARCHIVE_UNAVAILABLE", "trade_eligible": False}


def source_events(db_path: Path, symbol: str, category: str) -> dict:
    """Return bounded, hash-checked evidence for one category and one symbol."""
    if category not in CATEGORY_NAMES:
        raise ValueError("UNKNOWN_CALENDAR_CATEGORY")
    symbol = symbol.upper().removesuffix(".US")
    index = source_observations(db_path, symbol)
    entry = (index.get("categories") or {}).get(category)
    if entry is None:
        return {"status": index["status"], "category": category, "symbol": symbol,
                "events": [], "trade_eligible": False}
    digest = entry.get("source_hash")
    if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("SOURCE_HASH_INVALID")
    source = Path(db_path).parent / "option_event_sources" / f"{digest}.json"
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("SOURCE_HASH_MISMATCH")
    observation = json.loads(raw)
    events = [item for item in observation.get("matching_events", [])
              if category == "macro" or str(item.get("symbol") or "").upper().removesuffix(".US") == symbol]
    return {"status": "UNREVIEWED_SOURCE_OBSERVATIONS", "category": category, "symbol": symbol,
            "source_hash": digest, "source_url": entry.get("source_url"),
            "knowledge_as_of": entry.get("knowledge_as_of"), "query_start": entry.get("query_start"),
            "query_end": entry.get("query_end"), "pages_complete": entry.get("pages_complete"),
            "issues": entry.get("issues"), "event_count": len(events), "events": events[:100],
            "truncated": len(events) > 100, "trade_eligible": False}


class CalendarSourceRunner:
    """One bounded source collector owned by the existing Foundation process."""

    def __init__(self, db_path: Path, *, store: Path | None = None, context: Any | None = None,
                 max_requests: int = MAX_CALENDAR_REQUESTS_PER_RUN):
        self.db_path = Path(db_path)
        self.store = store or self.db_path.parent / "option_event_sources"
        self.context = context
        self.max_requests = max(6, min(int(max_requests), 48))
        # A calendar batch size is not permission to increase shared API usage.
        self.shared_source_window_cap = 12
        self.action_batch_size = 3
        self.calendar_reserved_requests = 6
        from .options_source_call import SourceCallGate
        self.source_call_gate = SourceCallGate()
        self.category_offset = 0

    def _context(self):
        if self.context is None:
            if not all(os.environ.get(key) for key in ("LONGBRIDGE_APP_KEY", "LONGBRIDGE_APP_SECRET", "LONGBRIDGE_ACCESS_TOKEN")):
                raise RuntimeError("CALENDAR_CREDENTIALS_UNAVAILABLE")
            from longbridge.openapi import HttpClient
            # SDK 4.4.1's typed calendar object drops next_date. Keep the raw JSON.
            self.context = HttpClient.from_apikey_env()
        return self.context

    def refresh(self, *, now: datetime | None = None, cancelled=lambda: False) -> dict:
        from .options_two_hour_data import universe

        current = now or datetime.now(UTC)
        market_day = current.astimezone(ZoneInfo("America/New_York")).date()
        end = market_day + timedelta(days=7)
        watch = universe(self.db_path)
        symbols = tuple(item["symbol"] for item in watch["items"] if item["identity_status"] == "verified"
                        and str(item["provider_symbol"]).endswith(".US"))
        context = self._context()
        from longbridge.openapi import CalendarCategory

        run = self.store / "runs" / f"{current.astimezone(UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
        run.mkdir(parents=True, exist_ok=False)
        requests = 0
        manifest = {"scope_hash": watch["scope_hash"], "manifest_count": len(watch["items"]),
                    "query_start": market_day.isoformat(), "query_end": end.isoformat(),
                    "requested_at": current.astimezone(UTC).isoformat(), "categories": {},
                    "trade_eligible": False, "approval_state": "SOURCE_OBSERVATION_ONLY"}
        categories = list(CATEGORY_NAMES)
        categories = categories[self.category_offset:] + categories[:self.category_offset]
        self.category_offset = (self.category_offset + 1) % len(categories)
        for position, category in enumerate(categories):
            if cancelled():
                break

            def fetch(name, start, stop):
                nonlocal requests
                if self.source_call_gate.snapshot()['in_flight']:
                    raise CalendarSourceInFlight()
                # Reserve one request for every remaining category.
                if requests >= self.max_requests - (len(categories) - position - 1):
                    raise CalendarBudgetDeferred()
                requests += 1
                if callable(getattr(context, "request", None)):
                    path = calendar_request_path(name, start, stop)
                    response = self.source_call_gate.call(lambda: context.request("get", path))
                    if not isinstance(response, dict):
                        raise ValueError("CALENDAR_RESPONSE_NOT_OBJECT")
                    return response
                return self.source_call_gate.call(lambda: context.finance_calendar(
                    getattr(CalendarCategory, CATEGORY_NAMES[name]), start.isoformat(), stop.isoformat(), market="US"))

            observation = collect_pages(fetch, category=category, start=market_day, end=end,
                                        symbols=symbols, cancelled=cancelled)
            source_file = run / f"{category}.json"
            source_file.write_text(json.dumps(observation, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            manifest["categories"][category] = {"file_sha256": hashlib.sha256(source_file.read_bytes()).hexdigest(),
                "pages_complete": observation["pages_complete"], "issues": observation["issues"],
                "event_count": len(observation["matching_events"])}
            (run / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if len(manifest["categories"]) != len(CATEGORY_NAMES):
            return {"status": "CANCELLED_PARTIAL", "run_ref": str(run), "trade_eligible": False,
                    "calendar_requests": requests, "request_cap": self.max_requests,
                    "categories_collected": len(manifest["categories"])}
        index = publish_observations(run, self.store)
        return {"status": "ARCHIVED_UNREVIEWED", "run_ref": str(run), "scope_hash": watch["scope_hash"],
                "categories_collected": len(index["categories"]),
                "source_complete_categories": sum(bool(row["pages_complete"]) for row in index["categories"].values()),
                "calendar_requests": requests, "request_cap": self.max_requests,
                "transport": "LONGBRIDGE_RAW_JSON" if callable(getattr(context, "request", None)) else "TYPED_CALENDAR_CONTEXT",
                "trade_eligible": False}
