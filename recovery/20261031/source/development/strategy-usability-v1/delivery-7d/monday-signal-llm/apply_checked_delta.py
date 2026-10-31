"""Verify a frozen delta; deployment requires a separate exact OWNER receipt."""
import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
from zipfile import ZipFile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def release_hashes(release):
    declared = {}
    for section in ('files','retained_source_hashes','frontend_files','configuration_hashes','source_fact_hashes'):
        for path, value in release.get(section, {}).items():
            expected = value['sha256'] if section == 'files' else value
            if path in declared and declared[path] != expected:
                raise ValueError('RELEASE_SECTION_HASH_CONFLICT: ' + path)
            declared[path] = expected
    return declared


def checked_path(path, root):
    path, root = Path(path).absolute(), Path(root).absolute()
    if not path.is_relative_to(root) or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('PATH_OUTSIDE_APPROVED_ROOT')
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError('REPARSE_PATH')
    return path


def verify_receipt(receipt, projection, recovery, root):
    if not (receipt.get('gate') == 'O-LAUNCH' and receipt.get('approved_by') == 'OWNER'
            and receipt.get('status') == 'APPROVED'
            and receipt.get('candidate_id') == projection['candidate_id']
            and receipt.get('candidate_payload_sha256') == projection['candidate_payload_sha256']
            and receipt.get('runtime_root') == str(root/'runtime')
            and receipt.get('continuity_receipt_sha256') == recovery['continuity']['receipt']['sha256']
            and receipt.get('scope') == 'SHADOW_STARTUP_RESEARCH_OBSERVATIONS_ONLY'):
        raise ValueError('EXACT_SHADOW_ACCEPTANCE_REQUIRED')
    for key in ('qualified_signal_authorized', 'source_facts_approved', 'orders_authorized',
                'system_clock_change_authorized', 's1_manual_policy_authorized', 'system_autostart_authorized'):
        if receipt.get(key) is not False:
            raise ValueError('UNEXPECTED_APPROVAL_SCOPE')
    evidence = receipt.get('human_decision_evidence') or {}
    if (evidence.get('source') != 'DIRECT_USER_REPLY' or not evidence.get('reference')
            or not evidence.get('answer')):
        raise ValueError('DIRECT_USER_REPLY_REQUIRED')
    scope = checked_path(evidence['scope_document'], root)
    if digest(scope) != evidence['scope_document_sha256']:
        raise ValueError('ACCEPTED_SCOPE_CHANGED')


def verify(projection_path, expected_hash, receipt_path=None, *, root=ROOT):
    root = Path(root).absolute()
    base = root/'source/development/workspace'
    projection_path = checked_path(projection_path, root)
    if digest(projection_path) != expected_hash:
        raise ValueError('PROJECTION_HASH_MISMATCH')
    projection = read(projection_path)
    entry_path = base/'config/local_workspace_entry.json'
    if digest(entry_path) != projection['base_entry_sha256']:
        raise ValueError('BASE_ENTRY_DRIFT')
    for key in ('release_manifest', 'recovery_manifest', 'base_release_manifest', 'base_recovery_manifest'):
        proof = projection[key]
        if digest(checked_path(proof['path'], root)) != proof['sha256']:
            raise ValueError('MANIFEST_HASH_MISMATCH')
    recovery = read(projection['recovery_manifest']['path'])
    payload = sha256(json.dumps({k: v for k, v in recovery.items()
        if k not in {'acceptance_receipt', 'final_runtime_accepted'}}, sort_keys=True,
        separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    if payload != projection['candidate_payload_sha256']:
        raise ValueError('CANDIDATE_PAYLOAD_MISMATCH')
    release = read(projection['release_manifest']['path'])
    declared = release_hashes(release)
    changed = {row['target']: row for row in projection['changes']}
    for relative, expected in declared.items():
        artifact = changed[relative]['payload'] if relative in changed else base/relative
        if digest(checked_path(artifact, root)) != expected:
            raise ValueError('PROJECTED_RELEASE_ARTIFACT_MISMATCH: ' + relative)
    targets = set()
    for row in projection['changes']:
        relative = Path(row['target'])
        python_or_config=relative.parts[0] in {'kquant','config'} and relative.suffix in {'.py','.json'}
        gateway=relative.as_posix()=='crypto/kquant_crypto/gateway.py'
        web=(relative.parts[:2] in {('web','dist'),('web','dist-unified'),('web','src')}
             and relative.suffix in {'.tsx','.ts','.css','.html','.js','.svg','.png','.ico','.woff','.woff2','.json','.map','.webmanifest'})
        if (relative.is_absolute() or '..' in relative.parts
                or not (python_or_config or gateway or web) or row['target'] in targets):
            raise ValueError('DELTA_TARGET_NOT_ALLOWED')
        targets.add(row['target'])
        target = checked_path(base/relative, root)
        source = checked_path(row['payload'], root)
        if digest(source) != row['sha256']:
            raise ValueError('PAYLOAD_DRIFT')
        if (digest(target) if target.is_file() else None) != row['previous_sha256']:
            raise ValueError('TARGET_DRIFT')
    receipt = None
    if receipt_path:
        receipt_path = checked_path(receipt_path, root)
        receipt = read(receipt_path)
        verify_receipt(receipt, projection, recovery, root)
    return projection, recovery, receipt


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix+'.deploy-pending')
    with temporary.open('xb') as stream:
        stream.write((json.dumps(value, ensure_ascii=True, indent=2)+'\n').encode())
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def apply(args):
    projection, recovery, receipt = verify(args.projection, args.projection_sha256, args.receipt)
    if not args.apply:
        return dict(candidate_id=projection['candidate_id'], validation='PASS', applied=False,
            exact_launch_receipt_present=receipt is not None, production_writes=0)
    if receipt is None:
        raise ValueError('EXACT_SHADOW_ACCEPTANCE_REQUIRED')
    output = Path(args.projection).parent
    state_path = output/'deployment-state.json'
    if state_path.exists():
        raise ValueError('PRIOR_DEPLOYMENT_STATE_REQUIRES_REVIEW')
    for name in ('deployment_tool', 'proposed_entry'):
        proof = projection.get(name) or {}
        if not proof.get('path') or digest(checked_path(proof['path'], ROOT)) != proof.get('sha256'):
            raise ValueError('DEPLOYMENT_ATTACHMENT_MISSING_OR_CHANGED: '+name)
    if Path(projection['deployment_tool']['path']).resolve() != Path(__file__).resolve():
        raise ValueError('DEPLOYMENT_TOOL_IDENTITY_MISMATCH')
    rollback = read(checked_path(args.rollback_receipt, ROOT))
    archive_path = checked_path(rollback['path'], ROOT)
    if digest(archive_path) != rollback['sha256']:
        raise ValueError('ROLLBACK_ARCHIVE_DRIFT')
    with ZipFile(archive_path) as archive:
        index = json.loads(archive.read('archive-index.json'))
        if (index.get('projection_sha256') != args.projection_sha256
                or index.get('candidate_payload_sha256') != projection['candidate_payload_sha256']
                or archive.testzip() is not None):
            raise ValueError('ROLLBACK_ARCHIVE_BINDING_INVALID')
        for name, expected in index['files'].items():
            if sha256(archive.read(name)).hexdigest() != expected:
                raise ValueError('ROLLBACK_ARCHIVE_FILE_CHANGED')
    assembly = read(args.assembly)
    if not (assembly.get('candidate_id') == projection['candidate_id']
            and assembly.get('candidate_payload_sha256') == projection['candidate_payload_sha256']
            and assembly.get('exact_candidate_binding') is True
            and assembly.get('continuous_60_minutes') is True
            and assembly.get('observation_assembly_pass') is True
            and not assembly.get('errors') and not assembly.get('child_processes_alive')):
        raise ValueError('MATCHING_ASSEMBLY_HOUR_REQUIRED')
    report = assembly['report']
    if digest(checked_path(report['path'], ROOT)) != report['sha256']:
        raise ValueError('ASSEMBLY_REPORT_DRIFT')
    if assembly.get('enqueue_to_commit_performance_pass') is not True and (
            'PERFORMANCE_NOT_PASSED' not in receipt.get('limitations_accepted', [])):
        raise ValueError('PERFORMANCE_LIMITATION_NOT_ACCEPTED')
    # Use the existing identity-aware stop and the existing five-role launch gate.
    host = r'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe'
    env = dict(os.environ, PSModulePath=r'C:\Windows\System32\WindowsPowerShell\v1.0\Modules;C:\Program Files\WindowsPowerShell\Modules')
    command = [host, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT/'Start-Local-KQUANT.ps1')]
    subprocess.run(command+['-Stop'], check=True, timeout=90, env=env)
    services = read(ROOT/'runtime/work/option_foundation/runtime/services.json')
    if services.get('state') != 'STOPPED':
        raise ValueError('STOP_NOT_CONFIRMED')
    verify(args.projection, args.projection_sha256, args.receipt)
    state = dict(candidate_id=projection['candidate_id'], started_at=datetime.now(UTC).isoformat(),
        state='STOPPED_APPLYING', replaced=[], business_databases_written=False)
    atomic_json(state_path, state)
    base = ROOT/'source/development/workspace'
    try:
        for row in projection['changes']:
            target = base/row['target']
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix+'.deploy-pending')
            with temporary.open('xb') as stream:
                stream.write(Path(row['payload']).read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            if digest(temporary) != row['sha256']:
                raise ValueError('STAGED_PAYLOAD_DRIFT')
            os.replace(temporary, target)
            state['replaced'].append(row['target'])
            atomic_json(state_path, state)
        accepted_path = output/'recovery-manifest-shadow-accepted.json'
        recovery.update(final_runtime_accepted=True,
            acceptance_receipt=dict(path=str(Path(args.receipt).resolve()), sha256=digest(args.receipt)))
        atomic_json(accepted_path, recovery)
        entry = read(projection['proposed_entry']['path'])
        entry.update(shadow_runtime_accepted=True, recovery_manifest=dict(path=str(accepted_path), sha256=digest(accepted_path)))
        atomic_json(base/'config/local_workspace_entry.json', entry)
        subprocess.run(command, check=True, timeout=60, env=env)
        subprocess.run(command+['-Start'], check=True, timeout=90, env=env)
        state.update(state='START_REQUESTED_REQUIRES_REAL_TEN_MINUTE_OBSERVATION', finished_at=datetime.now(UTC).isoformat())
    except Exception as exc:
        state.update(state='FAILED_REQUIRES_EXPLICIT_RECOVERY', error_type=type(exc).__name__)
        raise
    finally:
        atomic_json(state_path, state)
    return state


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--projection', type=Path, required=True)
    parser.add_argument('--projection-sha256', required=True)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--assembly', type=Path)
    parser.add_argument('--rollback-receipt', type=Path)
    parser.add_argument('--apply', action='store_true')
    arguments = parser.parse_args()
    if arguments.apply and (not arguments.receipt or not arguments.assembly or not arguments.rollback_receipt):
        parser.error('--apply requires an exact receipt, matched assembly, and rollback receipt')
    print(json.dumps(apply(arguments), ensure_ascii=True))
