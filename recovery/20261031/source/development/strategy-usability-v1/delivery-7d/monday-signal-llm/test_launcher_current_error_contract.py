"""Current sanitized error/lifecycle contract; original legacy failures retained."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[4]
BASE=ROOT/'source/development/workspace'


@pytest.mark.parametrize('case,code',[
    ('missing','SAFE_RECOVERY_REQUIRED'),
    ('forbidden','SAFE_RECOVERY_PATH_NOT_ON_APPROVED_LOCAL_DRIVE'),
    ('wrong_root','SAFE_RECOVERY_PREFLIGHT_FAILED'),
])
def test_real_launcher_records_safe_preflight_failure_without_loading_credentials(tmp_path,case,code):
    runtime=tmp_path/'runtime'
    args=[r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe','-NoProfile',
        '-ExecutionPolicy','Bypass','-File',str(BASE/'start_kquant_workspace.ps1'),
        '-RuntimeRoot',str(runtime),'-PythonExecutable',sys.executable,
        '-RecoveryLocalRoot',str(tmp_path),'-OptionsFoundation','-OneMinuteShadow','-NoBrowser']
    if case=='forbidden':
        args+=['-RecoveryManifest',r'F:\TEST_ONLY-never-open-manifest.json']
    if case=='wrong_root':
        manifest=tmp_path/'manifest.json'
        manifest.write_text(json.dumps(dict(test_only=True,code_root=str(tmp_path/'wrong'),
            runtime_root=str(runtime),approved_runtime_root=str(runtime))),encoding='ascii')
        args+=['-RecoveryManifest',str(manifest)]
    env=dict(os.environ,PSModulePath=r'C:\Windows\System32\WindowsPowerShell\v1.0\Modules;C:\Program Files\WindowsPowerShell\Modules')
    active=ROOT/'runtime/work/kquant_us.sqlite3'
    before=active.stat().st_mtime_ns
    result=subprocess.run(args,capture_output=True,text=True,timeout=15,env=env)
    assert result.returncode!=0
    assert 'FOUNDATION_LAUNCH_FAILED_PREFLIGHT_' in result.stderr
    events=[json.loads(line) for file in runtime.glob('work/option_foundation/runtime/lifecycle.*.jsonl')
        for line in file.read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    failed=[x for x in events if x.get('state')=='FAILED']
    assert len(failed)==1 and failed[0]['details']['code']==code
    assert all(x['stage']=='PREFLIGHT' for x in events)
    assert not list(runtime.rglob('*.sqlite3'))
    assert not list(runtime.rglob('stock-options-foundation.*'))
    assert active.stat().st_mtime_ns==before
