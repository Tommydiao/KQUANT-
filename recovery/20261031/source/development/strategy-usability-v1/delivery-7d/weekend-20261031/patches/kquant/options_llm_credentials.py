"""Shared, local-only credential loading for options research roles."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess


def credential_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "KQUANT" / "options_llm_key.dpapi"


def credential_source() -> str:
    return "WINDOWS_CURRENT_USER_DPAPI" if credential_path().exists() else "MISSING_LOCAL_DPAPI"


def api_key() -> str:
    path = credential_path()
    if not path.exists():
        return ""
    if os.name != "nt":
        return ""
    # A configured local credential fails closed, rather than falling back to an old key.
    script = """$ErrorActionPreference = 'Stop'
$p = Join-Path $env:LOCALAPPDATA 'KQUANT/options_llm_key.dpapi'
$s = ConvertTo-SecureString ([IO.File]::ReadAllText($p))
$b = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)
try { [Console]::Write([Runtime.InteropServices.Marshal]::PtrToStringBSTR($b)) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($b) }
"""
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""
