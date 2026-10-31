"""Restore only archived code after release verification rejected startup.

Never opens, replaces or rolls back a business database. The original guarded
entry must independently check old-schema compatibility before it can restart.
"""
import argparse
from datetime import UTC, datetime
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import subprocess
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = ROOT / 'source/development/workspace'


def digest(body):
    return sha256(body).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--projection', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('guarded_delta_paths', HERE / 'apply_accepted_delta.py')
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    path = guard.checked_path(args.projection, HERE / 'release')
    p = json.loads(path.read_bytes())
    state = json.loads((path.parent / 'deployment-state.json').read_bytes())
    if state['candidate_id'] != p['candidate_id'] or state['state'] != 'START_REQUESTED_REQUIRES_REAL_TEN_MINUTE_OBSERVATION':
        raise ValueError('ONLY_PRELAUNCH_FAILURE_RECOVERY_ALLOWED')
    command = "$p=@(Get-CimInstance Win32_Process | Where-Object {$_.CommandLine -match '-m kquant[.]dashboard|-m kquant_crypto[.]gateway|start_kquant_workspace[.]ps1' -and $_.Name -in @('python.exe','powershell.exe')});$l=@(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object {$_.LocalPort -in @(8001,8020)});if($p.Count -or $l.Count){exit 12}"
    subprocess.run([r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe',
        '-NoProfile', '-Command', command], check=True, timeout=15)
    receipt = json.loads((path.parent / 'delta-archive-receipt.json').read_bytes())
    archive_path = guard.checked_path(receipt['path'], path.parent)
    if digest(archive_path.read_bytes()) != receipt['sha256']:
        raise ValueError('ARCHIVE_CHANGED')
    writes = []
    with ZipFile(archive_path) as z:
        index = json.loads(z.read('archive-index.json'))
        if index['projection_sha256'] != digest(path.read_bytes()) or z.testzip() is not None:
            raise ValueError('ARCHIVE_BINDING_CHANGED')
        for name, expected in index['files'].items():
            if digest(z.read(name)) != expected:
                raise ValueError('ARCHIVE_MEMBER_CHANGED')
        current_entry = json.loads((BASE / 'config/local_workspace_entry.json').read_bytes())
        if current_entry['candidate_id'] != p['candidate_id']:
            raise ValueError('ACTIVE_ENTRY_CHANGED')
        for row in p['changes']:
            target = guard.checked_path(BASE / row['target'], BASE)
            if digest(target.read_bytes()) != row['sha256']:
                raise ValueError('INSTALLED_SOURCE_CHANGED')
            previous = row['previous_sha256']
            body = z.read('rollback/' + row['target']) if previous is not None else None
            if body is not None and digest(body) != previous:
                raise ValueError('PREVIOUS_SOURCE_HASH_MISMATCH')
            writes.append((target, body))
        entry_body = z.read('rollback/local_workspace_entry.json')
        if digest(entry_body) != p['base_entry_sha256']:
            raise ValueError('PREVIOUS_ENTRY_CHANGED')
        writes.append((BASE / 'config/local_workspace_entry.json', entry_body))
    result = dict(observed_at=datetime.now(UTC).isoformat(), failed_candidate=p['candidate_id'],
        previous_candidate=p['base_candidate'], source_files=len(writes), applied=False,
        business_database_opens=0, business_database_writes=0,
        reason='RELEASE_FRONTEND_HASH_SECTIONS_INCONSISTENT_NO_WORKER_STARTED')
    if args.apply:
        for target, body in writes:
            if body is None:
                target.unlink()
            else:
                temporary = target.with_suffix(target.suffix + '.restore-pending')
                with temporary.open('xb') as stream:
                    stream.write(body)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
        result.update(applied=True, state='CODE_RESTORED_ORIGINAL_GATE_REQUIRED_BEFORE_START')
        with (path.parent / 'prelaunch-code-recovery.json').open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
