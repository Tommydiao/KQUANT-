"""Actual PowerShell entry contracts; all process fixtures are TEST_ONLY."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from time import sleep

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOST = shutil.which('pwsh') or shutil.which('powershell')
pytestmark = pytest.mark.skipif(os.name != 'nt' or not HOST, reason='Windows host required')


def run(code, timeout=20):
    return subprocess.run([HOST, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
        '-Command', code], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)


def layout(tmp_path):
    code = tmp_path / 'source/development/workspace'
    (code / 'scripts').mkdir(parents=True)
    for name in ('FoundationLifecycle.ps1', 'Launch-FoundationDetached.ps1', 'Invoke-FoundationDetached.ps1'):
        shutil.copyfile(ROOT / 'scripts' / name, code / 'scripts' / name)
    return code


def test_real_preflight_failure_records_stage_without_business_or_children(tmp_path):
    code = layout(tmp_path)
    shutil.copyfile(ROOT / 'start_kquant_workspace.ps1', code / 'start_kquant_workspace.ps1')
    (code / 'config').mkdir()
    (code / 'config/safe_recovery_required.json').write_text('{}')
    data = tmp_path / 'runtime'
    result = run(f"& '{code / 'start_kquant_workspace.ps1'}' -OptionsFoundation -OneMinuteShadow -RuntimeRoot '{data}' -PythonExecutable '{sys.executable}'")
    assert result.returncode != 0
    rows = [json.loads(line) for p in (data / 'work/option_foundation/runtime').glob('lifecycle.*.jsonl')
            for line in p.read_text(encoding='utf-8-sig').splitlines()]
    assert [r['state'] for r in rows] == ['PREFLIGHT', 'FAILED', 'EXITED']
    assert all(r['stage'] == 'PREFLIGHT' for r in rows)
    assert all(r['run_session_id'] for r in rows)
    assert not (data / 'work/option_foundation/runtime/services.json').exists()
    assert not list(data.rglob('*.sqlite3'))
    assert not (code / 'work').exists()


def test_detached_host_and_dataroot_survive_requesting_host_exit(tmp_path):
    code = layout(tmp_path)
    data = tmp_path / 'runtime'
    data.mkdir()
    entry = tmp_path / 'Start-Local-KQUANT.ps1'
    marker = tmp_path / 'TEST_ONLY-alive.json'
    entry.write_text(f"""param([switch]$HostCheckOnly,[switch]$Start,[switch]$Foreground)
if($HostCheckOnly){{'{{"ready":true}}';exit 0}}
if(-not $Start -or -not $Foreground){{throw 'TEST_ONLY_FLAGS_REQUIRED'}}
@{{pid=$PID;at=[DateTimeOffset]::UtcNow.ToString('o');test_only=$true}} | ConvertTo-Json | Set-Content -LiteralPath '{marker}'
Start-Sleep -Seconds 12
""")
    launch = code / 'scripts/Launch-FoundationDetached.ps1'
    result = run(f"& '{launch}' -EntryScript '{entry}' -RuntimeRoot '{data}' -ExpectedEntrySHA256 ((Get-FileHash -LiteralPath '{entry}').Hash.ToLowerInvariant())")
    assert result.returncode == 0, result.stderr
    request = json.loads(result.stdout)
    try:
        assert request['host'].lower().endswith(Path(HOST).name.lower())
        assert request['system_task_created'] is False
        for _ in range(30):
            if marker.exists():
                break
            sleep(.1)
        assert marker.exists()
        # The initiating PowerShell process has already exited at subprocess.run return.
        status = run(f". '{ROOT / 'scripts/FoundationLifecycle.ps1'}'; Get-FoundationProcessIdentity {request['launcher_pid']} | ConvertTo-Json")
        assert json.loads(status.stdout)['created_at'] == request['launcher_identity']['created_at']
        assert list((data / 'work/logs').glob('detached.*.log'))
        assert not (code / 'work').exists()
    finally:
        identity = request['launcher_identity']
        run(f". '{ROOT / 'scripts/FoundationLifecycle.ps1'}'; $p=Get-FoundationProcessIdentity {identity['pid']}; if($p -and $p.created_at -eq '{identity['created_at']}'){{Stop-Process -Id {identity['pid']} -Force}}")


def test_owned_cleanup_does_not_touch_other_process(tmp_path):
    owned = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        result = run(f". '{ROOT / 'scripts/FoundationLifecycle.ps1'}'; $script:StartedServices=@([pscustomobject]@{{pid={owned.pid};identity=(Get-FoundationProcessIdentity {owned.pid})}}); $script:OwnedListenerIdentities=@(); Stop-FoundationOwnedServices")
        assert result.returncode == 0, result.stderr
        owned.wait(timeout=5)
        assert unrelated.poll() is None
    finally:
        for child in (owned, unrelated):
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)


def test_pid_identity_change_rejects_cleanup(tmp_path):
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        result = run(f"$ErrorActionPreference='Stop'; . '{ROOT / 'scripts/FoundationLifecycle.ps1'}'; $i=Get-FoundationProcessIdentity {child.pid}; $i.created_at='2000-01-01T00:00:00Z'; $script:StartedServices=@([pscustomobject]@{{pid={child.pid};identity=$i}}); $script:OwnedListenerIdentities=@(); Stop-FoundationOwnedServices")
        assert result.returncode != 0
        assert 'CLEANUP_PID_IDENTITY_CHANGED' in result.stderr
        assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=5)


def test_rejected_second_launcher_preserves_first_manifest(tmp_path):
    path = tmp_path / 'services.json'
    path.write_text('{"run_session_id":"first","state":"RUNNING"}')
    result = run(f". '{ROOT / 'scripts/FoundationLifecycle.ps1'}'; $script:FoundationOwnsMutex=$false; $serviceManifest='{path}'; Write-FoundationTerminalSnapshot 'STOPPED' 'SECOND_LAUNCH_REJECTED'")
    assert result.returncode == 0, result.stderr
    assert json.loads(path.read_text()) == {'run_session_id': 'first', 'state': 'RUNNING'}
