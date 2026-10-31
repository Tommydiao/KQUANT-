"""Bounded public HTTPS source checks for named event reviews.

Only reviewed URLs are fetched. A failed or changed source never extends a review.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import sqlite3
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import requests
from .bounded_sqlite import read_connection

MAX_BYTES = 512 * 1024
MAX_AGE_SECONDS = 900
REVIEW_POLICIES = frozenset({
    "EVENT-COVERAGE-V3-AUTOMATED-NORMAL-HUMAN-EXCEPTION",
    "EVENT-COVERAGE-ONE-MINUTE-SAME-DAY-V1",
    "EVENT-COVERAGE-OPENING-TREND-SAME-DAY-V1",
})


def _store(db_path: Path) -> Path:
    path = Path(db_path).parent / "option_event_sources" / "official"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(_store(db_path) / "checks.sqlite3", timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("""CREATE TABLE IF NOT EXISTS checks (
        source_url TEXT PRIMARY KEY, content_hash TEXT, checked_at TEXT NOT NULL,
        status TEXT NOT NULL, error_type TEXT, content_type TEXT)""")
    return connection


def _public_https(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.hostname
    if (parsed.scheme != "https" or not host or parsed.username or parsed.password
            or parsed.port not in (None, 443) or host.lower().endswith((".local", ".internal", ".test"))):
        raise ValueError("PUBLIC_HTTPS_SOURCE_REQUIRED")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None or host.lower() == "localhost":
        raise ValueError("PUBLIC_DOMAIN_SOURCE_REQUIRED")
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("PRIVATE_OR_UNRESOLVED_SOURCE")


def capture(db_path: Path, url: str, *, now: datetime | None = None) -> dict:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    try:
        _public_https(url)
        with requests.Session() as session:
            session.trust_env = False
            with session.get(url, timeout=5, allow_redirects=False, stream=True,
                             headers={"User-Agent": "KQUANT-event-source-check/1.0"}) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError("SOURCE_REDIRECT_OR_UNEXPECTED_STATUS")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type not in {"text/html", "text/plain", "application/pdf", "application/json", "text/calendar"}:
                    raise ValueError("SOURCE_CONTENT_TYPE_UNSUPPORTED")
                data = bytearray()
                for chunk in response.iter_content(chunk_size=16384):
                    data.extend(chunk)
                    if len(data) > MAX_BYTES:
                        raise ValueError("SOURCE_TOO_LARGE")
        if not data:
            raise ValueError("SOURCE_EMPTY")
        digest = hashlib.sha256(data).hexdigest()
        target = _store(db_path) / f"{digest}.bin"
        if not target.exists():
            target.write_bytes(data)
        outcome = {"source_url": url, "content_hash": digest, "checked_at": current.isoformat(),
                   "status": "VERIFIED", "content_type": content_type, "error_type": None}
    except (OSError, ValueError, requests.RequestException) as exc:
        outcome = {"source_url": url, "content_hash": None, "checked_at": current.isoformat(),
                   "status": "UNAVAILABLE", "content_type": None, "error_type": type(exc).__name__}
    with _connect(db_path) as connection:
        connection.execute("""INSERT INTO checks (source_url,content_hash,checked_at,status,error_type,content_type)
            VALUES (:source_url,:content_hash,:checked_at,:status,:error_type,:content_type)
            ON CONFLICT(source_url) DO UPDATE SET content_hash=excluded.content_hash,
                checked_at=excluded.checked_at,status=excluded.status,error_type=excluded.error_type,
                content_type=excluded.content_type""", outcome)
        connection.commit()
    return outcome


@lru_cache(maxsize=64)
def _archive_matches(path: str, digest: str, modified_ns: int) -> bool:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest


def source_check(db_path: Path, url: str, *, now: datetime | None = None) -> dict:
    path = Path(db_path).parent / "option_event_sources" / "official" / "checks.sqlite3"
    if not path.exists():
        return {"status": "NOT_CHECKED"}
    try:
        with read_connection(path, seconds=.15) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM checks WHERE source_url=?", (url,)).fetchone()
        if not row:
            return {"status": "NOT_CHECKED"}
        result = dict(row)
        age = ((now or datetime.now(UTC)).astimezone(UTC) -
               datetime.fromisoformat(row["checked_at"])).total_seconds()
        if age < 0 or age > MAX_AGE_SECONDS:
            result["status"] = "STALE"
        if result["status"] == "VERIFIED":
            digest = str(result.get("content_hash") or "")
            source = path.parent / f"{digest}.bin"
            if (len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
                    or not source.is_file() or not _archive_matches(str(source), digest, source.stat().st_mtime_ns)):
                result["status"] = "ARCHIVE_MISMATCH"
        result["age_seconds"] = round(age, 3)
        return result
    except (sqlite3.Error, OSError, ValueError, TimeoutError):
        return {"status": "UNAVAILABLE"}


def refresh_active_reviews(db_path: Path, *, limit: int = 16, now: datetime | None = None) -> dict:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    with sqlite3.connect(f"file:{Path(db_path).resolve().as_posix()}?mode=ro", uri=True) as connection:
        rows = connection.execute("""SELECT source_url,payload_json FROM option_event_coverage
            WHERE valid_until>? ORDER BY recorded_at DESC""", (current.isoformat(),)).fetchall()
    urls = set()
    invalid = 0
    for url, raw in rows:
        try:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("REVIEW_PAYLOAD_INVALID")
            if payload.get("v3_policy_id") in REVIEW_POLICIES:
                if not isinstance(url, str) or not url.strip():
                    raise ValueError("REVIEW_SOURCE_MISSING")
                urls.add(url)
        except (ValueError, TypeError):
            invalid += 1
    ordered = sorted(urls, key=lambda url: (source_check(db_path, url, now=current).get("checked_at") or "", url))
    results = [capture(db_path, url, now=current) for url in ordered[:max(0, min(limit, 48))]]
    return {"checked": len(results), "remaining": max(0, len(ordered) - len(results)),
            "invalid_reviews": invalid,
            "verified": sum(row["status"] == "VERIFIED" for row in results),
            "failed": sum(row["status"] != "VERIFIED" for row in results)}
