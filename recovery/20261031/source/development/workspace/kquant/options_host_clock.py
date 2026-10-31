"""Shared host-clock snapshot reader; system queries belong to the clock owner."""
from datetime import UTC, datetime
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from time import perf_counter


SCHEMA = "KQUANT_HOST_CLOCK_SNAPSHOT_V1"
SNAPSHOT_NAME = "host-clock.json"
MAX_SNAPSHOT_BYTES = 8192
MAX_SNAPSHOT_AGE_SECONDS = 900
PUBLIC_HOSTS = {"time.cloudflare.com", "time.windows.com", "time.google.com"}


def parse_status(text):
    def number(label):
        match = re.search(rf"^(?:{label}):\s*(-?\d+(?:\.\d+)?)", text, re.MULTILINE)
        value = float(match.group(1)) if match else None
        return value if value is not None and math.isfinite(value) else None

    leap = number(r"Leap Indicator|Leap \u6307\u793a\u7b26")
    stratum = number(r"Stratum|\u5c42\u6b21")
    error = number(r"Last Sync Error|\u4e0a\u6b21\u540c\u6b65\u9519\u8bef")
    age = number(r"Time since Last Good Sync Time|\u4e0a\u6b21\u6210\u529f\u540c\u6b65\u65f6\u95f4\u540e\u7684\u65f6\u95f4")
    match = re.search(r"^(?:Source|\u6e90):\s*([^\r\n]+)", text, re.MULTILINE)
    source = match.group(1).strip().split(",")[0].lower() if match else None
    # Only expose known public time hosts; never return raw system output.
    source = source if source in PUBLIC_HOSTS else None
    synced = leap == 0 and stratum is not None and 1 <= stratum <= 15 and error == 0 and source is not None
    state = "SYNCED_SYSTEM_REPORT" if synced and age is not None and 0 <= age <= 3600 else "UNVERIFIED"
    if synced and age is not None and age > 3600:
        state = "SYNC_REPORT_STALE"
    return dict(state=state, source=source, leap=leap, stratum=stratum,
                last_sync_error=error, last_sync_age_seconds=age,
                precision_verified=False, qualification_approval=False)


def read_system_status():
    """Explicit background-owner API; never called by status children or GET."""
    started = perf_counter()
    result = dict(state="UNAVAILABLE", precision_verified=False, qualification_approval=False)
    try:
        if sys.platform != "win32":
            result["error_code"] = "UNSUPPORTED_PLATFORM"
        else:
            reply = subprocess.run(["w32tm.exe", "/query", "/status", "/verbose"],
                capture_output=True, text=True, encoding="mbcs", errors="replace", timeout=.5,
                creationflags=subprocess.CREATE_NO_WINDOW, check=False)
            if reply.returncode == 0:
                result = parse_status(reply.stdout)
            else:
                result["error_code"] = "SYSTEM_QUERY_FAILED"
    except subprocess.TimeoutExpired:
        result["error_code"] = "SYSTEM_QUERY_TIMEOUT"
    except OSError:
        result["error_code"] = "SYSTEM_QUERY_UNAVAILABLE"
    result.update(checked_at=datetime.now(UTC).isoformat(), elapsed_ms=round((perf_counter() - started) * 1000, 3))
    return result


def _finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def read_status(*, path=None, now=None):
    """Read the owner's small atomic snapshot without refreshing or renewing it.

    Owner publication: {"schema": SCHEMA, "status": read_system_status()} at
    KQUANT_OPTION_FOUNDATION_ROOT/host-clock.json. Missing/stale data fails closed.
    """
    started = perf_counter()
    now = now or datetime.now(UTC)
    result = {"state": "UNAVAILABLE", "precision_verified": False, "qualification_approval": False,
              "checked_at": None, "snapshot_state": "UNAVAILABLE"}
    try:
        if path is None:
            root = Path(os.environ.get("KQUANT_OPTION_FOUNDATION_ROOT") or
                        Path(__file__).resolve().parents[1] / "work/option_foundation/runtime")
            path = root / SNAPSHOT_NAME
            if not path.resolve().is_relative_to(root.resolve()):
                raise ValueError("CLOCK_SNAPSHOT_PATH_INVALID")
        path = Path(path)
        if not path.is_file():
            result["error_code"] = "CLOCK_SNAPSHOT_MISSING"
        elif path.stat().st_size > MAX_SNAPSHOT_BYTES:
            result["error_code"] = "CLOCK_SNAPSHOT_TOO_LARGE"
        else:
            with path.open("rb") as stream:
                raw = stream.read(MAX_SNAPSHOT_BYTES + 1)
            if len(raw) > MAX_SNAPSHOT_BYTES:
                result["error_code"] = "CLOCK_SNAPSHOT_TOO_LARGE"
            else:
                packet = json.loads(raw)
                if not isinstance(packet, dict) or packet.get("schema") != SCHEMA:
                    raise ValueError("CLOCK_SNAPSHOT_SCHEMA_INVALID")
                status = packet["status"]
                if not isinstance(status, dict):
                    raise ValueError("CLOCK_SNAPSHOT_STATUS_INVALID")
                if status.get("state") not in {"UNAVAILABLE", "UNVERIFIED", "SYNCED_SYSTEM_REPORT", "SYNC_REPORT_STALE"}:
                    raise ValueError("CLOCK_SNAPSHOT_STATE_INVALID")
                checked = status["checked_at"]
                if not isinstance(checked, str) or len(checked) > 48:
                    raise ValueError("CLOCK_SNAPSHOT_TIMESTAMP_INVALID")
                checked_at = datetime.fromisoformat(checked)
                if checked_at.utcoffset() is None:
                    raise ValueError("CLOCK_SNAPSHOT_TIMESTAMP_UNZONED")
                age = (now - checked_at).total_seconds()
                result.update(checked_at=checked_at.astimezone(UTC).isoformat(),
                              snapshot_age_seconds=round(age, 3))
                if not 0 <= age <= MAX_SNAPSHOT_AGE_SECONDS:
                    result.update(snapshot_state="STALE", error_code="CLOCK_SNAPSHOT_STALE_OR_FUTURE")
                else:
                    source = status.get("source")
                    source = source if isinstance(source, str) and source in PUBLIC_HOSTS else None
                    numbers = {key: status.get(key) for key in (
                        "leap", "stratum", "last_sync_error", "last_sync_age_seconds")}
                    numbers = {key: value if _finite(value) else None for key, value in numbers.items()}
                    sync_age = numbers["last_sync_age_seconds"]
                    if sync_age is not None:
                        numbers["last_sync_age_seconds"] = sync_age + age
                    synced = (source is not None and numbers["leap"] == 0
                              and numbers["stratum"] is not None and 1 <= numbers["stratum"] <= 15
                              and numbers["last_sync_error"] == 0 and sync_age is not None and sync_age >= 0)
                    state = ("SYNCED_SYSTEM_REPORT" if numbers["last_sync_age_seconds"] <= 3600
                             else "SYNC_REPORT_STALE") if synced else "UNVERIFIED"
                    # Do not reinterpret a failed owner query as a good host report.
                    if status.get("state") == "UNAVAILABLE":
                        state = "UNAVAILABLE"
                    result.update(state=state, source=source, snapshot_state="FRESH", **numbers)
                    code = status.get("error_code")
                    if code in {"UNSUPPORTED_PLATFORM", "SYSTEM_QUERY_FAILED", "SYSTEM_QUERY_TIMEOUT", "SYSTEM_QUERY_UNAVAILABLE"}:
                        result["error_code"] = code
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        result.update(state="UNAVAILABLE", snapshot_state="UNAVAILABLE", error_code="CLOCK_SNAPSHOT_INVALID")
    result.update(read_checked_at=now.astimezone(UTC).isoformat(),
                  elapsed_ms=round((perf_counter() - started) * 1000, 3))
    return result
