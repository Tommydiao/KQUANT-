"""Read-only OS observation, independent of market data and business databases."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import socket
import subprocess
from functools import lru_cache

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "work/option_foundation/runtime/services.json"


@lru_cache(maxsize=1)
def system_boot_identity():
    """One bounded OS read per observer process, executed by the background lane."""
    if os.name != "nt":
        return {"state": "UNAVAILABLE", "error_type": "OS_OBSERVATION_UNSUPPORTED"}
    declared = os.environ.get("KQUANT_LAUNCHER_HOST")
    host = Path(declared) if declared else Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    if not host.is_absolute() or host.drive.upper() not in {"C:", "D:", "E:"} or host.name.lower() not in {"pwsh.exe", "powershell.exe"}:
        return {"state": "UNAVAILABLE", "error_type": "BOOT_HOST_UNCONFIRMED"}
    try:
        run = subprocess.run([str(host), "-NoProfile", "-NonInteractive", "-Command",
            "$ErrorActionPreference='Stop'; (Get-CimInstance Win32_OperatingSystem -OperationTimeoutSec 2).LastBootUpTime.ToUniversalTime().ToString('o')"],
            capture_output=True, text=True, timeout=4, creationflags=subprocess.CREATE_NO_WINDOW)
        started = _time(run.stdout.strip()) if run.returncode == 0 and len(run.stdout) < 128 else None
        if started is None:
            return {"state": "UNAVAILABLE", "error_type": "BOOT_OBSERVATION_INVALID", "returncode": run.returncode}
        return {"state": "VERIFIED", "started_at": started.isoformat(), "source": "WIN32_OPERATING_SYSTEM", "host": str(host)}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"state": "UNAVAILABLE", "error_type": type(exc).__name__}


def _time(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(UTC) if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def process_identity(pid: int) -> dict:
    if os.name != "nt":
        return {"pid": pid, "alive": None, "error": "OS_OBSERVATION_UNSUPPORTED"}
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        return {"pid": pid, "alive": False if error == 87 else None, "error": f"WIN32_{error}"}
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        size = wintypes.DWORD(32768)
        image = ctypes.create_unicode_buffer(size.value)
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(item) for item in times)) or not kernel.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
            return {"pid": pid, "alive": None, "error": "PROCESS_IDENTITY_UNAVAILABLE"}
        ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        created = datetime.fromtimestamp(ticks / 10_000_000 - 11_644_473_600, UTC)
        return {"pid": pid, "alive": True, "created_at": created.isoformat(), "executable": image.value}
    finally:
        kernel.CloseHandle(handle)


def listeners() -> list[dict]:
    if os.name != "nt":
        raise OSError("OS_OBSERVATION_UNSUPPORTED")
    api = ctypes.WinDLL("iphlpapi").GetExtendedTcpTable
    api.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL, wintypes.ULONG, wintypes.ULONG, wintypes.ULONG]
    size = wintypes.DWORD()
    api(None, ctypes.byref(size), True, 2, 3, 0)
    # Process tables can grow between calls. Retry once, without unbounded work.
    for _ in range(2):
        buffer = ctypes.create_string_buffer(size.value)
        result = api(buffer, ctypes.byref(size), True, 2, 3, 0)
        if result == 122:
            continue
        if result:
            raise OSError(f"TCP_TABLE_{result}")
        count = int.from_bytes(buffer.raw[:4], "little")
        rows = []
        for index in range(count):
            fields = (wintypes.DWORD * 6).from_buffer_copy(buffer.raw, 4 + index * 24)
            port = socket.ntohs(fields[2] & 0xffff)
            if port in (8001, 8020):
                rows.append({"port": port, "pid": int(fields[5])})
        return rows
    raise OSError("TCP_TABLE_CHANGED")


def identity_matches(expected, actual):
    before, after = _time(expected.get("created_at")), _time(actual.get("created_at"))
    return bool(actual.get("alive") and before and after and abs((before - after).total_seconds()) <= .001
                and str(expected.get("executable", "")).casefold() == str(actual.get("executable", "")).casefold()
                and int(expected.get("pid", 0)) == int(actual.get("pid", -1)))


def adjudicate(manifest, processes, ports, *, now=None, system_boot=None):
    now = now or datetime.now(UTC)
    checked = _time(manifest.get("checked_at"))
    age = (now - checked).total_seconds() if checked else None
    launcher = manifest.get("launcher_identity", {"pid": manifest.get("launcher_pid", 0)})
    actual = processes.get(int(launcher.get("pid", 0)), {})
    rows = manifest.get("listeners", [])
    missing = [port for port in (8001, 8020) if not any(row.get("port") == port for row in ports)]
    identity_ok = identity_matches(launcher, actual) and len(rows) == 2 and {r.get("port") for r in rows} == {8001, 8020}
    for row in rows:
        expected = row.get("identity", {"pid": row.get("pid", 0)})
        identity_ok = identity_ok and row.get("command_verified") is True and identity_matches(expected, processes.get(int(row.get("pid", 0)), {})) and {"port": row.get("port"), "pid": row.get("pid")} in ports
    reasons = []
    observed_boot = system_boot or {"state": "UNAVAILABLE"}
    boot_at = _time(observed_boot.get("started_at")) if observed_boot.get("state") == "VERIFIED" else None
    created_at = _time(launcher.get("created_at"))
    previous_boot = bool(boot_at and created_at and created_at < boot_at)
    recovery_reason = None
    if actual.get("alive") is False and len(missing) == 2:
        state = "STOPPED"
        reasons.append("LAUNCHER_AND_LISTENERS_ABSENT")
        if previous_boot:
            reasons.append("PREVIOUS_BOOT_NOT_RESTARTED")
            recovery_reason = "PREVIOUS_BOOT_NOT_RESTARTED"
    elif age is None or age < 0 or age > 30:
        state = "UNKNOWN_STALE"
        reasons.append("HEARTBEAT_TIME_CONFLICT" if age is not None and age < 0 else "HEARTBEAT_STALE")
    elif not identity_ok or missing:
        state = "DEGRADED"
        reasons.append("PROCESS_IDENTITY_OR_LISTENER_MISMATCH")
    elif manifest.get("state") != "RUNNING" or manifest.get("health_verified") is not True:
        state = "DEGRADED"
        reasons.append("HEALTH_NOT_VERIFIED")
    else:
        state = "RUNNING"
    return {"state": state, "reported_state": manifest.get("state"), "observed_at": now.isoformat(),
            "run_session_id": manifest.get("run_session_id"), "system_boot": observed_boot,
            "recorded_system_boot": manifest.get("system_boot"), "recovery_reason": recovery_reason,
            "exit_reason_source": "RECORDED_LIFECYCLE" if manifest.get("exit_reason") else "UNKNOWN",
            "observation_sources": ["PROCESS_CREATION_IDENTITY", "TCP_LISTENERS", "HEARTBEAT", "SYSTEM_BOOT"],
            "heartbeat_at": manifest.get("checked_at"), "heartbeat_age_seconds": round(age, 3) if age is not None else None,
            "process_identity_verified": bool(identity_ok), "listeners": ports, "reasons": reasons,
            "exit_reason": manifest.get("exit_reason") or ("UNKNOWN" if state == "STOPPED" else None),
            "backend_release": manifest.get("backend_release"), "backend_manifest_sha256": manifest.get("backend_manifest_sha256"),
            "market_data_checked": False, "database_accessed": False}


def observe(path=MANIFEST):
    try:
        if path.stat().st_size > 65536:
            raise ValueError("MANIFEST_TOO_LARGE")
        manifest = json.loads(path.read_text(encoding="utf-8-sig"))
        ids = {int(manifest.get("launcher_pid", 0))} | {int(r.get("pid", 0)) for r in manifest.get("listeners", [])}
        return adjudicate(manifest, {pid: process_identity(pid) for pid in ids if pid > 0}, listeners(),
                          system_boot=system_boot_identity())
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {"state": "UNAVAILABLE", "observed_at": datetime.now(UTC).isoformat(), "error_type": type(exc).__name__,
                "exit_reason": "UNKNOWN", "market_data_checked": False, "database_accessed": False}


def attach(payload):
    if not os.getenv("KQUANT_OPTION_FOUNDATION_ROOT"):
        return payload
    value = observe(Path(os.environ["KQUANT_OPTION_FOUNDATION_ROOT"]) / "services.json")
    payload["service_observation"] = value
    if value["state"] != "RUNNING" and "snapshot" in payload:
        payload["snapshot"] = {**payload["snapshot"], "state": "STALE", "error_type": "SERVICE_RUNTIME_UNCONFIRMED"}
        payload["candidates"] = []
    return payload
