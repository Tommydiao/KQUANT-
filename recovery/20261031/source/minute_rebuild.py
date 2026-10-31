"""Isolated, quote-only historical minute reconstruction with durable evidence.

Offline planning never reads credentials. Live workers use inherited environment
variables only. No production database, execution context, or account API is used.
"""
from __future__ import annotations

import argparse
from collections import Counter, OrderedDict
from contextlib import contextmanager
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT / "development/workspace"
CACHE_ROOT = ROOT / "minute-rebuild"
DEFAULT_MANIFEST = ROOT / "evidence/retained-watchlist.json"
UTC = timezone.utc
SCHEMA = "KQUANT_ISOLATED_MINUTE_REBUILD_V1"
PREFIX = "KQUANT_REBUILD_REPORT="
FIELDS = ("open", "high", "low", "close", "volume", "turnover")
STOP_CATEGORIES = {"AUTHENTICATION", "TOKEN_EXPIRED", "ACCESS_DENIED",
                   "INVALID_SIGNATURE", "INVALID_APP_KEY", "IP_NOT_ALLOWED",
                   }
RETRY_CATEGORIES = {"RATE_LIMIT", "TIMEOUT", "CONNECTION", "SERVER_ERROR"}


class CacheIntegrityError(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def native_fingerprint(row):
    # Preserve native strings in evidence while treating equivalent Decimal
    # spellings as the same economic observation for conflict detection.
    normalized = {}
    for key in FIELDS:
        value = Decimal(row[key])
        with localcontext() as context:
            context.prec = max(1, len(value.as_tuple().digits))
            normalized[key] = str(value.normalize())
    return digest({"open_at": row["open_at"], **normalized})


def aware(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("TIMEZONE_REQUIRED")
    return parsed.astimezone(UTC)


def clock_functions():
    if str(WORKSPACE) not in sys.path:
        sys.path.insert(0, str(WORKSPACE))
    from kquant.market_clock import is_trading_day, session_bounds_utc
    return is_trading_day, session_bounds_utc


def timestamp_profile(name="aware-only", evidence_path=None):
    if name == "aware-only":
        if evidence_path:
            raise ValueError("TIMESTAMP_EVIDENCE_WITHOUT_NAIVE_CONTRACT")
        return {"name": "AWARE_ONLY", "naive_timezone": None, "evidence_sha256": None}
    if name != "verified-naive-asia-shanghai" or not evidence_path:
        raise ValueError("NAIVE_TIMESTAMP_CONTRACT_REQUIRES_VERIFIED_EVIDENCE")
    evidence_file = Path(evidence_path)
    # A local secret file must never be accepted as contract evidence.
    if evidence_file.name.startswith(".env"):
        raise ValueError("INVALID_TIMESTAMP_EVIDENCE_PATH")
    raw = evidence_file.read_bytes()
    evidence = json.loads(raw)
    wheel = ROOT / "environment/wheels/longbridge-4.4.1-cp312-cp312-win_amd64.whl"
    if (evidence.get("status") != "VERIFIED" or evidence.get("sdk_version") != "4.4.1"
            or evidence.get("naive_timezone") != "Asia/Shanghai"
            or not evidence.get("verification_method") or not evidence.get("verified_at")
            or not isinstance(evidence.get("sources"), list) or not evidence["sources"]
            or evidence.get("sdk_wheel_sha256") != hashlib.sha256(wheel.read_bytes()).hexdigest()):
        raise ValueError("NAIVE_TIMESTAMP_CONTRACT_NOT_BOUND_TO_VERIFIED_SDK")
    aware(evidence["verified_at"])
    return {"name": "VERIFIED_SDK_NAIVE_ASIA_SHANGHAI", "naive_timezone": "Asia/Shanghai",
            "evidence_sha256": hashlib.sha256(raw).hexdigest()}


def build_plan(manifest, now, *, session_count=20, symbols=None, profile=None, calendar=None):
    now = aware(now)
    if not 1 <= session_count <= 40:
        raise ValueError("SESSION_COUNT_OUT_OF_BOUNDS")
    is_session, bounds = calendar or clock_functions()
    day = now.astimezone(ZoneInfo("America/New_York")).date()
    sessions = []
    for _ in range(180):
        if is_session(day):
            opening, closing = map(aware, bounds(day))
            if closing <= now:
                sessions.append({"session": day.isoformat(), "opening": opening.isoformat(),
                                 "closing": closing.isoformat(),
                                 "expected_minutes": int((closing - opening).total_seconds() // 60)})
                if len(sessions) == session_count:
                    break
        day -= timedelta(days=1)
    if len(sessions) != session_count:
        raise ValueError("CLOSED_SESSION_WINDOW_UNAVAILABLE")
    profile = profile or timestamp_profile()
    manifest_sha = digest(manifest)
    selected = set(symbols) if symbols else None
    items = manifest.get("items", [])
    names = [item.get("symbol") for item in items]
    if len(names) != len(set(names)):
        raise ValueError("DUPLICATE_MANIFEST_SYMBOL")
    if selected and selected - set(names):
        raise ValueError("SYMBOL_OUTSIDE_RETAINED_WATCHLIST")
    eligible, unresolved = [], []
    for item in items:
        if selected is not None and item.get("symbol") not in selected:
            continue
        symbol, provider = item.get("symbol"), item.get("provider_symbol")
        if not isinstance(symbol, str) or not symbol or len(symbol) > 128 or any(ord(c) < 32 for c in symbol):
            raise ValueError("INVALID_MANIFEST_SYMBOL")
        if (item.get("identity_status") != "verified" or not isinstance(provider, str)
                or not re.fullmatch(r"[A-Z0-9.-]+\.US", provider)):
            unresolved.append({"symbol": symbol, "state": "IDENTITY_UNRESOLVED"})
            continue
        if not re.fullmatch(r"[A-Z0-9.-]+", symbol):
            raise ValueError("INVALID_VERIFIED_MANIFEST_SYMBOL")
        eligible.append({"symbol": symbol, "provider_symbol": provider})
    eligible.sort(key=lambda item: (item["symbol"] != "NVDA", item["symbol"]))
    contract = {"period": "Min_1", "adjustment": "NoAdjust", "trade_sessions": "Intraday",
                "native_fields": list(FIELDS), "timestamp_profile": profile,
                "currency_scope": "US_STOCK_NATIVE_FIELDS_UNIT_PROOF_REQUIRED_FOR_ADMISSION"}
    tasks = []
    for session in sessions:  # All symbols' most recent closed session first.
        for item in eligible:
            task = {**item, **session, "manifest_sha256": manifest_sha, "contract": contract}
            task["task_id"] = digest(task)
            tasks.append(task)
    return {"schema": SCHEMA, "planned_at": now.isoformat(), "market_data_only": True,
            "production_started": False, "old_business_continuity": "UNKNOWN",
            "manifest_sha256": manifest_sha, "eligible_symbols": len(eligible),
            "unresolved_symbols": unresolved, "sessions_newest_first": sessions,
            "tasks": tasks, "theoretical_slots": sum(t["expected_minutes"] for t in tasks)}


def raw_rows(candles):
    result = []
    for candle in candles:
        if isinstance(candle, dict):
            stamp = candle.get("timestamp", candle.get("raw_timestamp"))
            getter = candle.get
        else:
            stamp = getattr(candle, "timestamp", None)
            getter = lambda key, default=None: getattr(candle, key, default)
        row = {"raw_timestamp": stamp.isoformat() if isinstance(stamp, datetime) else str(stamp),
               "raw_timestamp_type": type(stamp).__name__}
        for field in FIELDS:
            value = getter(field)
            row[field] = str(value) if value is not None else None
        result.append(row)
    return result


def validate_page(task, rows, requested_at, received_at):
    requested, received = aware(requested_at), aware(received_at)
    opening, closing = aware(task["opening"]), aware(task["closing"])
    if requested < closing or received < requested:
        raise ValueError("REQUEST_NOT_AFTER_SESSION_OR_RECEIPT_BEFORE_REQUEST")
    profile = task["contract"]["timestamp_profile"]
    accepted, rejected, seen, fingerprints, conflicts = [], [], set(), {}, set()
    for ordinal, row in enumerate(rows):
        reasons, normalized = [], None
        try:
            if row.get("raw_timestamp_type") != "datetime":
                raise ValueError("NON_NATIVE_DATETIME")
            stamp = datetime.fromisoformat(row["raw_timestamp"])
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                if (profile.get("name") != "VERIFIED_SDK_NAIVE_ASIA_SHANGHAI"
                        or profile.get("naive_timezone") != "Asia/Shanghai"
                        or not profile.get("evidence_sha256")):
                    raise ValueError("UNVERIFIED_NAIVE_TIMESTAMP")
                stamp = stamp.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            normalized = stamp.astimezone(UTC)
            if (normalized.second or normalized.microsecond
                    or not opening <= normalized < closing
                    or (normalized - opening).total_seconds() % 60):
                reasons.append("OUTSIDE_REGULAR_MINUTE_GRID")
            if normalized + timedelta(minutes=1) > requested:
                reasons.append("NOT_CLOSED_AT_REQUEST")
        except (TypeError, ValueError, OverflowError) as exc:
            reasons.append(str(exc) if str(exc) in {"UNVERIFIED_NAIVE_TIMESTAMP", "NON_NATIVE_DATETIME"}
                           else "INVALID_TIMESTAMP")
        values = {}
        for field in FIELDS:
            try:
                value = Decimal(row[field]) if row.get(field) is not None else None
                if value is None or not value.is_finite():
                    raise ValueError()
                if value < 0 or (field in FIELDS[:4] and value <= 0):
                    raise ValueError()
                values[field] = value
            except (InvalidOperation, ValueError, TypeError):
                reasons.append("INVALID_NATIVE_" + field.upper())
        if all(key in values for key in FIELDS[:4]):
            if not (values["low"] <= min(values["open"], values["close"])
                    <= max(values["open"], values["close"]) <= values["high"]):
                reasons.append("INVALID_OHLC")
        if normalized is not None and normalized in seen:
            reasons.append("DUPLICATE_MINUTE")
            if all(key in values for key in FIELDS):
                duplicate = {"open_at": normalized.isoformat(), **{key: row[key] for key in FIELDS}}
                if fingerprints[normalized] != native_fingerprint(duplicate):
                    conflicts.add(normalized.isoformat())
        if reasons:
            rejected.append({"ordinal": ordinal, "raw_timestamp": row.get("raw_timestamp"),
                             "reasons": sorted(set(reasons))})
        else:
            seen.add(normalized)
            accepted.append({"open_at": normalized.isoformat(), "raw_timestamp": row["raw_timestamp"],
                             "timestamp_profile": profile, **{key: row[key] for key in FIELDS},
                             "native_fields_preserved": True,
                             "native_field_units_admission_verified": False})
            fingerprints[normalized] = native_fingerprint(accepted[-1])
    grid = [opening + timedelta(minutes=i) for i in range(task["expected_minutes"])]
    missing = [stamp.isoformat() for stamp in grid if stamp not in seen]
    at_limit = len(rows) >= 1000
    state = ("PAGE_AT_PROVIDER_LIMIT" if at_limit else "COMPLETE" if not missing and not rejected
             else "EMPTY" if not rows else "PARTIAL")
    return {"state": state, "provider_rows": len(rows), "accepted_unique_minutes": len(accepted),
            "expected_minutes": len(grid), "missing_minutes": missing, "rejected_rows": rejected,
            "rejection_counts": dict(Counter(reason for row in rejected for reason in row["reasons"])),
            "page_at_provider_limit": at_limit, "accepted_rows": accepted,
            "conflicting_minutes": sorted(conflicts),
            "historical_page_complete": state == "COMPLETE", "production_admission_verified": False}


@contextmanager
def writer_lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    stream = (directory / "writer.lock").open("a+b")
    stream.seek(0, os.SEEK_END)
    if stream.tell() == 0:
        stream.write(b"0")
        stream.flush()
    stream.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise CacheIntegrityError("ANOTHER_REBUILD_WRITER_ACTIVE") from None
    try:
        yield
    finally:
        stream.seek(0)
        if os.name == "nt":
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def atomic_json(path, value):
    atomic_bytes(path, canonical(value))


def atomic_bytes(path, raw):
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    with temp.open("wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


class PageStore:
    """Single-writer immutable pages, with a repairable atomic projection index."""
    def __init__(self, directory):
        self.directory = Path(directory)
        self.pages = self.directory / "pages"
        self.index_path = self.directory / "coverage-index.json"
        self._page_cache = OrderedDict()
        self._validation_cache = OrderedDict()
        self.pages.mkdir(parents=True, exist_ok=True)
        self.index = {"schema": SCHEMA, "tasks": {}, "page_metadata": {}, "quota_blocks": []}
        if self.index_path.exists():
            try:
                self.index = json.loads(self.index_path.read_bytes())
                if self.index.get("schema") != SCHEMA or not isinstance(self.index.get("tasks"), dict):
                    raise ValueError()
            except (ValueError, TypeError):
                raise CacheIntegrityError("COVERAGE_INDEX_INVALID") from None
        # A child killed between page commit and index commit leaves a safe orphan.
        # Recover it from its content-bound task; never overwrite an indexed page.
        self.index.setdefault("page_metadata", {})
        self.index.setdefault("quota_blocks", [])
        self.index.setdefault("access_blocks", [])
        indexed = {page_sha for entry in self.index["tasks"].values() for page_sha in entry["pages"]}
        paths = {path.stem: path for path in self.pages.glob("*.json")}
        if indexed - paths.keys():
            raise CacheIntegrityError("INDEXED_PAGE_MISSING")
        changed, recovered_tasks = False, {}
        for page_sha in sorted(paths.keys() - indexed):
            path = paths[page_sha]
            page = self.read_page(path.stem)
            entry = self.index["tasks"].setdefault(page["task"]["task_id"], {"pages": []})
            if path.stem not in entry["pages"]:
                entry["pages"].append(path.stem)
                changed = True
                recovered_tasks[page["task"]["task_id"]] = page["task"]
                self._index_page_metadata(path.stem, page)
        if changed:
            for task_id, task in recovered_tasks.items():
                self.index["tasks"][task_id]["coverage"] = self.compact_coverage(task)
        if changed or not self.index_path.exists():
            self.commit_index()

    def read_page(self, page_sha):
        if not re.fullmatch(r"[0-9a-f]{64}", page_sha):
            raise CacheIntegrityError("INVALID_PAGE_HASH")
        path = self.pages / f"{page_sha}.json"
        try:
            stat = path.stat()
            observed = (stat.st_size, stat.st_mtime_ns, stat.st_ino)
            cached = self._page_cache.get(page_sha)
            if cached is not None and cached[0] == observed:
                self._page_cache.move_to_end(page_sha)
                return cached[1]
            raw = path.read_bytes()
        except OSError:
            raise CacheIntegrityError("INDEXED_PAGE_MISSING") from None
        if hashlib.sha256(raw).hexdigest() != page_sha:
            raise CacheIntegrityError("IMMUTABLE_PAGE_CHANGED")
        try:
            page = json.loads(raw)
            task = dict(page["task"])
            task_id = task.pop("task_id")
            if page.get("schema") != SCHEMA or digest(task) != task_id:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise CacheIntegrityError("IMMUTABLE_PAGE_BINDING_INVALID") from None
        self._page_cache[page_sha] = (observed, page)
        self._page_cache.move_to_end(page_sha)
        while len(self._page_cache) > 64:
            evicted, _ = self._page_cache.popitem(last=False)
            self._validation_cache.pop(evicted, None)
        return page

    def _index_page_metadata(self, page_sha, page):
        self.index["page_metadata"][page_sha] = {
            "provider_symbol": page["task"]["provider_symbol"], "requested_at": page["requested_at"],
            "provider_scope_sha256": page.get("provider_scope_sha256"),
            "request_success": page["error"] is None}

    def commit_index(self):
        atomic_json(self.index_path, self.index)

    def append(self, task, rows, requested_at, received_at, *, error=None, provider_scope_sha256=None):
        if provider_scope_sha256 is not None and not re.fullmatch(r"[0-9a-f]{64}", provider_scope_sha256):
            raise ValueError("INVALID_PROVIDER_SCOPE_SHA256")
        validation = validate_page(task, rows, requested_at, received_at) if error is None else None
        page = {"schema": SCHEMA, "record_kind": "HISTORICAL_REDOWNLOAD_NOT_OLD_BUSINESS_RECOVERY",
                "task": task, "requested_at": aware(requested_at).isoformat(),
                "received_at": aware(received_at).isoformat(), "rows": rows,
                "validation": validation, "error": error, "production_admission_verified": False,
                "provider_scope_sha256": provider_scope_sha256,
                "old_business_continuity": "UNKNOWN"}
        raw = canonical(page)
        page_sha = hashlib.sha256(raw).hexdigest()
        target = self.pages / f"{page_sha}.json"
        if target.exists():
            if target.read_bytes() != raw:
                raise CacheIntegrityError("IMMUTABLE_PAGE_CHANGED")
        else:
            # Exclusive write to a temporary name, then atomic publish. Orphaned
            # temporary files from killed workers are never treated as pages.
            temp = target.with_suffix(f".{os.getpid()}.tmp")
            with temp.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, target)
        entry = self.index["tasks"].setdefault(task["task_id"], {"pages": []})
        if page_sha not in entry["pages"]:
            entry["pages"].append(page_sha)
        self._index_page_metadata(page_sha, page)
        entry.pop("quota_deferred", None)
        entry["coverage"] = self.compact_coverage(task)
        self.commit_index()
        return page_sha

    def compact_coverage(self, task):
        coverage = self.coverage(task)
        return {key: value for key, value in coverage.items()
                if key not in {"missing_minutes", "conflicting_minutes"}} | {
                    "missing_minutes_count": len(coverage["missing_minutes"]),
                    "conflicting_minutes_count": len(coverage["conflicting_minutes"]),
                    "missing_minutes_sha256": digest(coverage["missing_minutes"]),
                    "conflicting_minutes_sha256": digest(coverage["conflicting_minutes"])}

    def projected_coverage(self, task):
        """Fast reporting projection; never used to admit data or skip a request."""
        entry = self.index["tasks"].get(task["task_id"], {})
        coverage = entry.get("coverage")
        if coverage is not None:
            return dict(coverage)
        deferred = entry.get("quota_deferred")
        return {"state": "QUOTA_DEFERRED" if deferred else "PENDING", "accepted_unique_minutes": 0,
                "expected_minutes": task["expected_minutes"], "missing_minutes_count": task["expected_minutes"],
                "conflicting_minutes_count": 0, "page_count": len(entry.get("pages", [])),
                "source_quality_warning_pages": 0, "last_error": None,
                "historical_market_complete": False, "production_admission_verified": False}

    def _validated_page(self, page_sha, page):
        # read_page first checks immutable file metadata; a changed file is
        # rehashed before this cached within-process validation can be reused.
        observed = self._page_cache[page_sha][0]
        cached = self._validation_cache.get(page_sha)
        if cached is not None and cached[0] == observed:
            return cached[1]
        validation = validate_page(page["task"], page["rows"], page["requested_at"], page["received_at"])
        self._validation_cache[page_sha] = (observed, validation)
        return validation

    def used_symbol_sources(self, now, scope_sha256):
        """Only current-month, same-app successful immutable request receipts."""
        if scope_sha256 is None:
            return {}
        current = aware(now)
        utc_month = current.strftime("%Y-%m")
        cn_month = current.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")
        if utc_month != cn_month:
            return {}  # Do not guess the provider's month-boundary timezone.
        candidates = {}
        for page_sha, meta in self.index["page_metadata"].items():
            if meta.get("provider_scope_sha256") != scope_sha256 or not meta.get("request_success"):
                continue
            requested = aware(meta["requested_at"])
            if (requested.strftime("%Y-%m") == utc_month
                    and requested.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m") == cn_month):
                prior = candidates.get(meta["provider_symbol"])
                if prior is None or requested > prior[0]:
                    candidates[meta["provider_symbol"]] = (requested, page_sha)
        sources = {}
        for provider_symbol, (_, page_sha) in candidates.items():
            page = self.read_page(page_sha)
            if (page.get("provider_scope_sha256") != scope_sha256 or page["error"] is not None
                    or page["task"]["provider_symbol"] != provider_symbol):
                raise CacheIntegrityError("MONTHLY_USED_SYMBOL_PROOF_CHANGED")
            requested = aware(page["requested_at"])
            if (requested.strftime("%Y-%m") != utc_month
                    or requested.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m") != cn_month):
                raise CacheIntegrityError("MONTHLY_USED_SYMBOL_PROOF_CHANGED")
            sources.setdefault(page["task"]["provider_symbol"], []).append(page_sha)
        return sources

    def active_quota_block(self, now, scope_sha256):
        if scope_sha256 is None:
            return None
        current = aware(now)
        months = (current.strftime("%Y-%m"), current.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m"))
        for block in reversed(self.index["quota_blocks"]):
            if block.get("provider_scope_sha256") != scope_sha256 or tuple(block.get("months", [])) != months:
                continue
            page = self.read_page(block["page_sha256"])
            requested = aware(page["requested_at"])
            actual_months = (requested.strftime("%Y-%m"),
                             requested.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m"))
            if (page.get("provider_scope_sha256") != scope_sha256 or page["error"] is None
                    or page["error"]["error_category"] != "HISTORY_MONTHLY_SYMBOL_QUOTA"
                    or actual_months != months):
                raise CacheIntegrityError("MONTHLY_QUOTA_PROOF_CHANGED")
            return block
        return None

    def record_quota_block(self, page_sha, now, scope_sha256):
        current = aware(now)
        block = {"provider_scope_sha256": scope_sha256, "page_sha256": page_sha,
                 "months": [current.strftime("%Y-%m"), current.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")]}
        self.index["quota_blocks"].append(block)
        self.commit_index()
        return block

    def active_denied_symbols(self, now, scope_sha256):
        if scope_sha256 is None:
            return set()
        month = aware(now).strftime("%Y-%m")
        denied = set()
        for block in self.index["access_blocks"]:
            if block["provider_scope_sha256"] != scope_sha256 or block["month_utc"] != month:
                continue
            page = self.read_page(block["page_sha256"])
            if (page.get("provider_scope_sha256") != scope_sha256 or page["error"] is None
                    or page["error"]["error_category"] != "NO_QUOTE_ACCESS"
                    or page["task"]["provider_symbol"] != block["provider_symbol"]
                    or aware(page["requested_at"]).strftime("%Y-%m") != month):
                raise CacheIntegrityError("SYMBOL_ACCESS_PROOF_CHANGED")
            denied.add(block["provider_symbol"])
        return denied

    def record_access_block(self, task, page_sha, now, scope_sha256):
        self.index["access_blocks"].append({"provider_scope_sha256": scope_sha256,
                                           "provider_symbol": task["provider_symbol"],
                                           "page_sha256": page_sha, "month_utc": aware(now).strftime("%Y-%m")})
        self.commit_index()

    def mark_quota_deferred(self, task, block):
        entry = self.index["tasks"].setdefault(task["task_id"], {"pages": []})
        entry["quota_deferred"] = block
        if "coverage" in entry and not entry["coverage"].get("historical_market_complete"):
            entry["coverage"]["state"] = "QUOTA_DEFERRED"

    def coverage(self, task):
        page_shas = self.index["tasks"].get(task["task_id"], {}).get("pages", [])
        chosen, conflicts, errors, capped_pages = {}, set(), [], 0
        successful_pages, warning_pages = 0, 0
        for page_sha in page_shas:
            page = self.read_page(page_sha)
            if page["task"] != task:
                raise CacheIntegrityError("PAGE_TASK_BINDING_CHANGED")
            if page["error"] is not None:
                errors.append(page["error"])
                continue
            # Revalidate original native values on every resume, rather than
            # trusting the stored validation or an index complete flag.
            validation = self._validated_page(page_sha, page)
            successful_pages += 1
            warning_pages += bool(validation["rejected_rows"])
            if validation["page_at_provider_limit"]:
                capped_pages += 1
                continue  # A capped single-day page cannot establish coverage.
            conflicts.update(validation["conflicting_minutes"])
            for row in validation["accepted_rows"]:
                stamp = row["open_at"]
                fingerprint = native_fingerprint(row)
                if stamp in chosen and chosen[stamp] != fingerprint:
                    conflicts.add(stamp)
                else:
                    chosen[stamp] = fingerprint
        opening = aware(task["opening"])
        grid = [(opening + timedelta(minutes=i)).isoformat() for i in range(task["expected_minutes"])]
        missing = [stamp for stamp in grid if stamp not in chosen or stamp in conflicts]
        complete = not missing and not conflicts and bool(successful_pages)
        return {"state": "CONFLICT" if conflicts else "COMPLETE" if complete
                else "PAGE_AT_PROVIDER_LIMIT" if capped_pages else "PARTIAL" if chosen
                else "NO_QUOTE_ACCESS" if errors and errors[-1]["error_category"] == "NO_QUOTE_ACCESS"
                else "PROVIDER_ERROR" if errors else "EMPTY" if successful_pages else "PENDING",
                "accepted_unique_minutes": len(chosen) - len(conflicts),
                "expected_minutes": len(grid), "missing_minutes": missing,
                "conflicting_minutes": sorted(conflicts), "page_count": len(page_shas),
                "successful_pages": successful_pages, "last_error": errors[-1] if errors else None,
                "source_quality_warning_pages": warning_pages,
                "historical_market_complete": complete, "production_admission_verified": False}


def safe_error(exc):
    from probe_minute_history import safe_provider_error
    return safe_provider_error(exc)


def execute_plan(plan, store, fetch, *, max_requests=2, max_attempts=2, max_page_attempts=3,
                 request_spacing=1.0, now=lambda: datetime.now(UTC), sleeper=time.sleep,
                 provider_scope_sha256=None, deadline_monotonic=None, monotonic=time.monotonic,
                 retry_no_quote_access=False):
    if not 1 <= max_requests <= 4000 or not 1 <= max_attempts <= 3 or not 1 <= max_page_attempts <= 5:
        raise ValueError("REQUEST_OR_RETRY_BUDGET_OUT_OF_BOUNDS")
    if request_spacing < 1.0:
        raise ValueError("REQUEST_SPACING_BELOW_ONE_SECOND")
    report = {"schema": SCHEMA, "status": "BATCH_FINISHED", "requests": 0, "completed_tasks": 0,
              "skipped_complete": 0, "partial_final": 0, "conflicting_tasks": 0,
              "market_data_only": True, "production_started": False,
              "old_business_continuity": "UNKNOWN", "results": [], "no_quote_access": 0,
              "quota_restricted": False, "quota_deferred_tasks": 0, "skipped_no_quote_access": 0,
              "provider_scope_kind": "APP_KEY_SHA256" if provider_scope_sha256 else "UNBOUND",
              "provider_scope_sha256": provider_scope_sha256}
    last_started = None
    prior_starts = [aware(meta["requested_at"]) for meta in store.index["page_metadata"].values()
                    if meta.get("provider_scope_sha256") == provider_scope_sha256]
    if prior_starts:
        last_started = max(prior_starts)
    block = store.active_quota_block(now(), provider_scope_sha256)
    known_sources = store.used_symbol_sources(now(), provider_scope_sha256) if block else {}
    denied_symbols = (set() if retry_no_quote_access else store.active_denied_symbols(now(), provider_scope_sha256))
    def quota_report():
        report["quota_restricted"] = True
        report["quota_scope"] = {"provider_scope_sha256": provider_scope_sha256,
                                  "months_utc_and_asia_shanghai": block["months"],
                                  "block_page_sha256": block["page_sha256"],
                                  "known_provider_symbols_and_proof_pages": known_sources,
                                  "unscoped_or_other_month_pages_excluded": True}
    if block:
        quota_report()
    def finish(reason=None):
        if reason:
            report["stop_reason"] = reason
            report["status"] = reason
        if block and not report["status"].startswith("BLOCKED_"):
            report["status"] = "MONTHLY_QUOTA_RESTRICTED"
        store.commit_index()  # Batch deferred markers once, rather than 2,000 replacements.
        return report
    def time_available(delay=0.0):
        return deadline_monotonic is None or monotonic() + delay < deadline_monotonic
    # Select unfinished work from the reporting projection before auditing old
    # completed tasks. Every task actually skipped as complete below is still
    # revalidated, but a small batch need not audit the entire archive before
    # making progress on its next 48 requests. Each partition keeps session order.
    pending_tasks, cached_complete_tasks = [], []
    for task in plan["tasks"]:
        (cached_complete_tasks if store.projected_coverage(task)["historical_market_complete"]
         else pending_tasks).append(task)
    report["cached_complete_tasks_not_selected_first"] = len(cached_complete_tasks)
    for task in pending_tasks + cached_complete_tasks:
        if not time_available():
            return finish("RUN_TIME_BUDGET_REACHED")
        projected = store.projected_coverage(task)
        # Quota and known per-symbol denials do not require expensive revalidation
        # of pages we are prohibited from requesting in this batch.
        if task["provider_symbol"] in denied_symbols:
            report["skipped_no_quote_access"] += 1
            continue
        if block and task["provider_symbol"] not in known_sources:
            if not projected["historical_market_complete"]:
                store.mark_quota_deferred(task, block)
                report["quota_deferred_tasks"] += 1
            continue
        coverage = store.coverage(task)
        if coverage["historical_market_complete"]:
            report["skipped_complete"] += 1
            continue
        if coverage["state"] == "CONFLICT":
            report["conflicting_tasks"] += 1
            continue
        if coverage["successful_pages"] >= max_page_attempts:
            report["partial_final"] += 1
            continue
        if report["requests"] >= max_requests:
            return finish("REQUEST_BUDGET_REACHED")
        for attempt in range(max_attempts):
            if report["requests"] >= max_requests:
                return finish("REQUEST_BUDGET_REACHED")
            if last_started is not None:
                delay = max(0.0, request_spacing - (aware(now()) - last_started).total_seconds())
                if not time_available(delay):
                    return finish("RUN_TIME_BUDGET_REACHED")
                sleeper(delay)
            if not time_available():
                return finish("RUN_TIME_BUDGET_REACHED")
            requested = aware(now())
            last_started = requested
            report["requests"] += 1
            error = None
            try:
                candles = fetch(task["provider_symbol"], date.fromisoformat(task["session"]))
                rows = raw_rows(candles)
            except Exception as exc:
                error, rows = safe_error(exc), []
            received = aware(now())
            page_sha = store.append(task, rows, requested, received, error=error,
                                    provider_scope_sha256=provider_scope_sha256)
            coverage = store.coverage(task)
            report["results"].append({"symbol": task["symbol"], "session": task["session"],
                                      "page_sha256": page_sha, "state": coverage["state"],
                                      "accepted_unique_minutes": coverage["accepted_unique_minutes"],
                                      "missing_minutes": len(coverage["missing_minutes"]),
                                      "error": error})
            if error is None:
                report["completed_tasks"] += int(coverage["historical_market_complete"])
                validation = store.read_page(page_sha)["validation"]
                if validation["rejection_counts"].get("UNVERIFIED_NAIVE_TIMESTAMP"):
                    report.update(status="BLOCKED_TIMESTAMP_CONTRACT", blocked_symbol=task["symbol"])
                    return finish()
                if validation["page_at_provider_limit"]:
                    report.update(status="BLOCKED_SINGLE_DAY_PAGE_AT_LIMIT", blocked_symbol=task["symbol"])
                    return finish()
                if provider_scope_sha256 is not None:
                    known_sources.setdefault(task["provider_symbol"], []).append(page_sha)
                    if block:
                        quota_report()
                break
            category = error["error_category"]
            if category in STOP_CATEGORIES:
                report.update(status="BLOCKED_" + category, blocked_symbol=task["symbol"])
                # Authentication remains a global stop even during restricted continuation.
                store.commit_index()
                return report
            if category == "NO_QUOTE_ACCESS":
                report["no_quote_access"] += 1
                denied_symbols.add(task["provider_symbol"])
                store.record_access_block(task, page_sha, received, provider_scope_sha256)
                break
            if category == "HISTORY_MONTHLY_SYMBOL_QUOTA":
                block = store.record_quota_block(page_sha, received, provider_scope_sha256)
                known_sources = store.used_symbol_sources(received, provider_scope_sha256)
                quota_report()
                break
            if category not in RETRY_CATEGORIES or attempt + 1 >= max_attempts:
                break
            delay = 30.0 if category == "RATE_LIMIT" else 2.0 * (attempt + 1)
            if not time_available(delay):
                return finish("RUN_TIME_BUDGET_REACHED")
            sleeper(delay)
    return finish()


def summarize(plan, store=None, *, revalidate=False):
    states, minutes, missing = Counter(), 0, 0
    for task in plan["tasks"]:
        coverage = ((store.coverage(task) if revalidate else store.projected_coverage(task)) if store else
                    {"state": "PENDING", "accepted_unique_minutes": 0, "missing_minutes_count": task["expected_minutes"]})
        states[coverage["state"]] += 1
        minutes += coverage["accepted_unique_minutes"]
        missing += len(coverage["missing_minutes"]) if "missing_minutes" in coverage else coverage["missing_minutes_count"]
    return {"eligible_symbols": plan["eligible_symbols"], "unresolved_symbols": plan["unresolved_symbols"],
            "sessions_newest_first": [s["session"] for s in plan["sessions_newest_first"]],
            "task_count": len(plan["tasks"]), "theoretical_slots": plan["theoretical_slots"],
            "accepted_unique_minutes": minutes, "missing_minutes": missing,
            "task_states": dict(states), "production_admission_verified": False,
            "coverage_basis": "IMMUTABLE_PAGES_REVALIDATED" if revalidate else "ATOMIC_INDEX_REPORTING_PROJECTION"}


def export_coverage_matrix(plan, store):
    fields = ("symbol", "provider_symbol", "session", "state", "accepted_unique_minutes",
              "expected_minutes", "missing_minutes_count", "conflicting_minutes_count",
              "page_count", "source_quality_warning_pages", "last_error_category",
              "production_admission_verified")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    for task in plan["tasks"]:
        coverage = store.projected_coverage(task)
        writer.writerow({"symbol": task["symbol"], "provider_symbol": task["provider_symbol"],
                         "session": task["session"], "state": coverage["state"],
                         "accepted_unique_minutes": coverage["accepted_unique_minutes"],
                         "expected_minutes": coverage["expected_minutes"],
                         "missing_minutes_count": coverage["missing_minutes_count"],
                         "conflicting_minutes_count": coverage["conflicting_minutes_count"],
                         "page_count": coverage["page_count"],
                         "source_quality_warning_pages": coverage["source_quality_warning_pages"],
                         "last_error_category": (coverage["last_error"] or {}).get("error_category"),
                         "production_admission_verified": False})
    for item in plan["unresolved_symbols"]:
        for session in plan["sessions_newest_first"]:
            writer.writerow({"symbol": item["symbol"], "session": session["session"],
                             "state": "IDENTITY_UNRESOLVED", "production_admission_verified": False})
    target = store.directory / "coverage-matrix.csv"
    atomic_bytes(target, stream.getvalue().encode("utf-8-sig"))
    return str(target)


def run_live_worker(args, plan, directory):
    worker_started = time.monotonic()
    required = ("LONGBRIDGE_APP_KEY", "LONGBRIDGE_APP_SECRET", "LONGBRIDGE_ACCESS_TOKEN")
    if not all(os.environ.get(key) for key in required):
        return {"status": "BLOCKED_INHERITED_CREDENTIALS_MISSING", "requests": 0}
    scope_sha256 = hashlib.sha256(os.environ["LONGBRIDGE_APP_KEY"].encode("utf-8")).hexdigest()
    from longbridge.openapi import Config, QuoteContext, Period, AdjustType, TradeSessions
    context = None
    def fetch(provider_symbol, session):
        nonlocal context
        if context is None:
            config = Config.from_apikey(*(os.environ[key] for key in required), enable_print_quote_packages=False)
            context = QuoteContext(config)
        return context.history_candlesticks_by_date(provider_symbol, Period.Min_1, AdjustType.NoAdjust,
                                                   session, session, trade_sessions=TradeSessions.Intraday)
    with writer_lock(directory):
        store = PageStore(directory)
        report = execute_plan(plan, store, fetch, max_requests=args.max_requests,
                              max_attempts=args.max_attempts, max_page_attempts=args.max_page_attempts,
                              provider_scope_sha256=scope_sha256,
                              deadline_monotonic=worker_started + args.run_seconds,
                              retry_no_quote_access=args.retry_no_quote_access)
        report["coverage"] = summarize(plan, store)
        report["worker_elapsed_seconds"] = round(time.monotonic() - worker_started, 3)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("dry-plan", "bounded-live"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--sessions", type=int, default=20)
    parser.add_argument("--symbols", help="Comma-separated subset of the retained watchlist")
    parser.add_argument("--as-of", help="Timezone-aware planning instant, default actual UTC now")
    parser.add_argument("--cache-name", default="default")
    parser.add_argument("--timestamp-contract", choices=("aware-only", "verified-naive-asia-shanghai"), default="aware-only")
    parser.add_argument("--timestamp-evidence", type=Path)
    parser.add_argument("--max-requests", type=int, default=2)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--max-page-attempts", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=int, default=55)
    parser.add_argument("--run-seconds", type=float, default=45,
                        help="Worker processing budget; leave at least five seconds for receipt/parent recovery")
    parser.add_argument("--retry-no-quote-access", action="store_true",
                        help="Explicitly retry previously denied symbols after permissions have changed")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", args.cache_name):
        parser.error("Invalid cache name")
    if args.manifest.name.startswith(".env"):
        parser.error("Invalid manifest path")
    if not 10 <= args.timeout_seconds <= 3600:
        parser.error("Timeout must be 10..3600 seconds")
    if not 1 <= args.run_seconds <= args.timeout_seconds - 5:
        parser.error("Run budget must leave at least five seconds before the parent timeout")
    directory = CACHE_ROOT / args.cache_name
    expected_cache = ROOT.resolve() / "minute-rebuild"
    if CACHE_ROOT.resolve() != expected_cache or not directory.resolve().is_relative_to(expected_cache):
        parser.error("Cache alias resolves outside the isolated reconstruction directory")
    if args.worker and args.mode != "bounded-live":
        parser.error("A live worker requires bounded-live mode")
    profile = timestamp_profile(args.timestamp_contract, args.timestamp_evidence)
    manifest = json.loads(args.manifest.read_bytes())
    as_of = aware(args.as_of) if args.as_of else datetime.now(UTC)
    if args.mode == "bounded-live" and as_of > datetime.now(UTC):
        parser.error("Future live planning instant is not allowed")
    plan = build_plan(manifest, as_of, session_count=args.sessions,
                      symbols=args.symbols.split(",") if args.symbols else None, profile=profile)
    if args.worker:
        try:
            report = run_live_worker(args, plan, directory)
        except CacheIntegrityError as exc:
            report = {"status": "CACHE_INTEGRITY_BLOCKED", "reason": str(exc), "requests": None}
        except Exception as exc:
            report = {"status": "WORKER_FAILED", **safe_error(exc)}
        print(PREFIX + json.dumps(report, ensure_ascii=False))
        return
    with writer_lock(directory):
        store = PageStore(directory)
        plans = directory / "plans"
        plans.mkdir(exist_ok=True)
        plan_sha = digest(plan)
        plan_path = plans / f"{plan_sha}.json"
        if not plan_path.exists():
            with plan_path.open("xb") as stream:
                stream.write(canonical(plan))
        report = {"status": "OFFLINE_PLAN_READY", "requests": 0, "plan_sha256": plan_sha,
                  "plan_path": str(plan_path), "cache_directory": str(directory),
                  "market_data_only": True, "production_started": False,
                  "old_business_continuity": "UNKNOWN",
                  "coverage": summarize(plan, store)}
        report["coverage_matrix"] = export_coverage_matrix(plan, store)
    if args.mode == "bounded-live":
        child_args = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:], "--worker"]
        if not args.as_of:
            child_args.extend(["--as-of", as_of.isoformat()])
        try:
            completed = subprocess.run(child_args, capture_output=True, text=True,
                                       encoding="utf-8", errors="replace", timeout=args.timeout_seconds)
            payloads = [line[len(PREFIX):] for line in completed.stdout.splitlines() if line.startswith(PREFIX)]
            live_report = json.loads(payloads[-1]) if payloads else {"status": "WORKER_FAILED", "returncode": completed.returncode}
        except subprocess.TimeoutExpired:
            live_report = {"status": "WORKER_TIMED_OUT", "timeout_seconds": args.timeout_seconds,
                           "child_terminated": True, "requests": None}
        report.update(live_report)
        # Reload after a completed/killed child to recover atomically committed pages.
        with writer_lock(directory):
            store = PageStore(directory)
            report["coverage"] = summarize(plan, store)
            report["coverage_matrix"] = export_coverage_matrix(plan, store)
    receipts = directory / "receipts"
    receipts.mkdir(exist_ok=True)
    receipt_path = receipts / (datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    with receipt_path.open("xb") as stream:
        stream.write(canonical(report))
    report["receipt_path"] = str(receipt_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
