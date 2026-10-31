"""Metadata-only receipt/path/service check; no business DB, key, SDK or restart."""
from datetime import UTC,datetime
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from bootstrap import HERE,BASE

ROOT=BASE.parents[2]


def record():
    start=datetime.now(UTC).isoformat()
    entry_path=BASE/'config/local_workspace_entry.json'
    entry=json.loads(entry_path.read_text(encoding='utf-8-sig'))
    manifests={}
    for key in ('runtime_manifest','recovery_manifest'):
        ref=entry[key]
        p=Path(ref['path'])
        if p.drive.upper()=='F:': raise ValueError('FORBIDDEN_DRIVE')
        manifests[key]=dict(path=str(p),expected_sha256=ref['sha256'],
            actual_sha256=sha256(p.read_bytes()).hexdigest())
    script="""$ErrorActionPreference='Stop'
$listeners=@(Get-NetTCPConnection -State Listen | Where-Object {$_.LocalPort -in 8001,8020,8193,8194} | Select-Object LocalAddress,LocalPort,OwningProcess)
$saved=Get-Content -LiteralPath 'E:\\kquant 1007\\KQUANT-Resume-Latest\\runtime\\work\\option_foundation\\runtime\\services.json' -Raw | ConvertFrom-Json
$ids=@($saved.launcher_pid)+@($saved.launches | ForEach-Object {$_.pid})
$processes=@(foreach($ident in $ids){Get-Process -Id $ident -ErrorAction SilentlyContinue | Select-Object Id,ProcessName,@{n='CreatedUtc';e={$_.StartTime.ToUniversalTime().ToString('o')}},Path})
@{observed_at=[DateTimeOffset]::UtcNow.ToString('o');listeners=$listeners;original_pid_matches=$processes;saved=$saved} | ConvertTo-Json -Depth 12
"""
    p=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],
        capture_output=True,text=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
    observation=json.loads(p.stdout) if p.returncode==0 else {'state':'OBSERVATION_UNAVAILABLE','exit_code':p.returncode}
    result=dict(started_at=start,finished_at=datetime.now(UTC).isoformat(),entry=entry,
        entry_sha256=sha256(entry_path.read_bytes()).hexdigest(),manifests=manifests,
        actual=observation,seven_day_verdict='FAIL_PRESERVED',production_writes=0,api_calls=0,
        role_map=json.loads((ROOT/'runtime/config/new-epoch-store-paths.json').read_text(encoding='utf-8-sig')),
        limitations=['sequential metadata observations, not atomic snapshot','does not open business DBs'])
    out=HERE/'evidence'
    out.mkdir(exist_ok=True)
    target=out/('baseline-'+datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')+'.json')
    target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'evidence':str(target),'observation_exit':p.returncode,
        'listeners':observation.get('listeners'),'manifest_matches':all(x['expected_sha256']==x['actual_sha256'] for x in manifests.values())}))


if __name__=='__main__': record()
