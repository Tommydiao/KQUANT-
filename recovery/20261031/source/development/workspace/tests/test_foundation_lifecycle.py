"""Exercise the actual Windows PowerShell file contract, not a Python substitute."""
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(os.name != "nt", reason="Windows launcher")
def test_json_creation_and_atomic_replacement(tmp_path):
    script = ROOT / "scripts/FoundationLifecycle.ps1"
    target = tmp_path / "snapshot.json"
    code = f". '{script}'; Write-FoundationJson '{target}' @{{generation=1}}; Write-FoundationJson '{target}' @{{generation=2}}"
    run = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", code], capture_output=True, timeout=10)
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    assert json.loads(target.read_text()) == {"generation": 2}
    assert not Path(str(target) + ".tmp").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows launcher")
def test_locked_destination_preserves_last_snapshot_and_error_fallback(tmp_path):
    script = ROOT / "scripts/FoundationLifecycle.ps1"
    target = tmp_path / "snapshot.json"
    code = f"""
$ErrorActionPreference='Stop'
$env:LOCALAPPDATA='{tmp_path}'
. '{script}'
Write-FoundationJson '{target}' @{{generation=1}}
$stream=[IO.File]::Open('{target}',[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::None)
try {{
  try {{ Write-FoundationJson '{target}' @{{generation=2}}; exit 7 }}
  catch {{ Write-FoundationFailureFallback 'DEGRADED' 'HEARTBEAT_STORAGE_WRITE_FAILED' }}
}} finally {{ $stream.Dispose() }}
"""
    run = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", code], capture_output=True, timeout=10)
    assert run.returncode == 0, run.stderr.decode(errors="replace")
    assert json.loads(target.read_text()) == {"generation": 1}
    files = list((tmp_path / "KQUANT/runtime-incidents").glob("*.jsonl"))
    assert len(files) == 1
    evidence = json.loads(files[0].read_text().strip())
    assert evidence["state"] == "DEGRADED"
    assert evidence["health_verified"] is False
    assert evidence["reason"] == "HEARTBEAT_STORAGE_WRITE_FAILED"
