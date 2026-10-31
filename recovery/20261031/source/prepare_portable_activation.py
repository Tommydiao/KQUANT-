"""Prepare one active copy per preserved role, never launch or approve production."""
import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sys
from time import monotonic

from prepare_local_epoch import ordinary

ROLES = {'main': 'work/kquant_us.sqlite3',
         'full_watch': 'work/options_full_watch/full_watch.sqlite3',
         'opening_research': 'work/options_one_minute/opening_trend_research.sqlite3',
         'signal_copilot': 'work/options_signal_copilot/signal_copilot.sqlite3'}


def hash_file(path, deadline):
    value = sha256()
    before = path.stat()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            if monotonic() >= deadline:
                raise TimeoutError('PREPARATION_BUDGET_EXHAUSTED')
            value.update(block)
    after = path.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('FILE_CHANGED_DURING_HASH')
    return value.hexdigest()


def record(path, value):
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != value:
            raise ValueError('EXISTING_RECORD_DIFFERENT_NO_OVERWRITE')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=True)


def finalize_binding(root, request_path, result_path):
    """Materialize observed activation facts and paths, not a release acceptance."""
    from kquant.recovery_activation import new_epoch_contract
    from kquant.recovery_preflight import canonical_hash
    for path in (request_path, result_path):
        ordinary(path, root)
    request = json.loads(request_path.read_text(encoding='utf-8'))
    result = json.loads(result_path.read_text(encoding='utf-8'))
    runtime = ordinary(root / 'runtime', root)
    if (request['runtime_root'] != str(runtime) or not result.get('ok')
            or result.get('can_launch') is not False or result.get('owner_acceptance_written') is not False):
        raise ValueError('OBSERVED_ACTIVATION_REQUIRED_NOT_LAUNCH')
    _, boundary = new_epoch_contract(request, runtime, [root], monotonic() + 5, False)
    facts = {r['role']: r for r in result['activation_receipts']}
    rows = request['databases']
    if len(facts) != 5 or set(facts) != {*ROLES, 'minute'} or len(rows) != 5:
        raise ValueError('EXACT_FIVE_ROLE_OBSERVATIONS_REQUIRED')
    out = ordinary(result_path.parent / ('bound-' + hash_file(result_path, monotonic() + 5)[:16]), root)
    out.mkdir(exist_ok=True)
    def ref(path):
        return {'path': str(path), 'sha256': hash_file(path, monotonic() + 5)}
    for row in rows:
        fact = facts[row['role']]
        if fact.get('test_only') or fact['database_path'] != row['path']:
            raise ValueError('ACTIVATION_ROLE_PATH_MISMATCH')
        ordinary(Path(row['path']), runtime)
        if row['role'] == 'minute' and fact.get('epoch_boundary') != boundary:
            raise ValueError('OBSERVED_EPOCH_MISMATCH')
        proof_path = out / (row['role'] + '-activation.json')
        record(proof_path, fact)
        row['activation_receipt'] = ref(proof_path)
    stores = {r['role']: r['path'] for r in rows}
    binding = {'schema': 'KQUANT_NEW_EPOCH_RUNTIME_PATHS_V1', 'runtime_root': str(runtime),
        'epoch_id': boundary['epoch_id'], 'session': boundary['session'], 'minute_path': stores['minute'],
        'opening_research_path': stores['opening_research'], 'stores': stores,
        'data_scope_acceptance_sha256': boundary['data_scope_acceptance_sha256']}
    binding_path = ordinary(runtime / 'config/new-epoch-store-paths.json', runtime)
    record(binding_path, binding)
    continuity = {'status': 'NEW_EPOCH_OLD_RECORDS_UNKNOWN', 'old_position_continuity': 'UNKNOWN',
        'unresolved_old_records': boundary['unresolved_old_records'], 'epoch_boundary': boundary,
        'database_receipts': {r['role']: r['receipt']['sha256'] for r in rows if r['role'] != 'minute'},
        'activation_receipts': {r['role']: r['activation_receipt']['sha256'] for r in rows},
        'watermarks': {role: fact['watermarks'] for role, fact in facts.items()}}
    continuity_path = out / 'continuity.json'
    record(continuity_path, continuity)
    package = {**request, 'databases': rows, 'runtime_path_binding': ref(binding_path),
        'continuity': {'status': continuity['status'], 'reconciled_roles': sorted(ROLES),
                       'receipt': ref(continuity_path)},
        'can_launch': False, 'qualified_signal_authorized': False, 'final_runtime_accepted': False}
    record(out / 'bound-data-materials.json', package)
    return {'materials': str(out / 'bound-data-materials.json'), 'runtime_path_binding': ref(binding_path),
            'can_launch': False, 'old_position_continuity': 'UNKNOWN'}


def prepare(root, review_path, acceptance_path, out, execute=False):
    root = root.absolute()
    for path in (root, review_path, acceptance_path, out):
        ordinary(path, root)
    sys.path.insert(0, str(root / 'source/development/workspace'))
    from kquant.recovery_activation import new_epoch_contract, produce
    deadline = monotonic() + 600
    review = json.loads(review_path.read_text(encoding='utf-8-sig'))
    declaration = review['declaration']
    if review['root'] != str(root) or declaration['runtime_root'] != str(root / 'runtime'):
        raise ValueError('LOCAL_ROOT_MISMATCH')
    from kquant.recovery_preflight import canonical_hash
    if canonical_hash(declaration) != review['declaration_sha256']:
        raise ValueError('DECLARATION_HASH_MISMATCH')
    if not execute:
        return {'preview': True, 'runtime_root': declaration['runtime_root'],
                'roles': ROLES, 'can_launch': False}
    out.mkdir(parents=True, exist_ok=True)
    declaration_path = ordinary(out / 'epoch-declaration.json', root)
    record(declaration_path, declaration)
    def ref(path):
        return {'path': str(path), 'sha256': hash_file(path, deadline)}
    request = {'schema': 'KQUANT_NEW_EPOCH_ACTIVATION_REQUEST_V1',
        'runtime_root': declaration['runtime_root'], 'approved_runtime_root': declaration['runtime_root'],
        'epoch_declaration': ref(declaration_path), 'data_scope_acceptance': ref(acceptance_path)}
    runtime = ordinary(root / 'runtime', root)
    minute, boundary = new_epoch_contract(request, runtime, [root], monotonic() + 5, False)
    if not minute.is_file():
        raise ValueError('EXISTING_APPROVED_EPOCH_REQUIRED_NO_CREATION')
    restore_path = ordinary(root / 'computer-handoff-restore-receipt.json', root)
    restore = json.loads(restore_path.read_text(encoding='utf-8-sig'))
    if (restore.get('schema') != 'KQUANT_PORTABLE_COMPUTER_HANDOFF_RESTORE_V1'
            or restore.get('restored') is not True or restore.get('inputs_verified') is not True
            or restore.get('preserved_snapshots') != str(root / 'preserved-stores')):
        raise ValueError('VERIFIED_LOCAL_RESTORE_REQUIRED')
    stores = {r['role']: r for r in restore['core_restore']['stores']}
    if set(stores) != set(ROLES):
        raise ValueError('EXACT_FOUR_PRESERVED_STORES_REQUIRED')
    if shutil.disk_usage(root).free < sum(r['bytes'] for r in stores.values()) + 1024**3:
        raise ValueError('INSUFFICIENT_SPACE')
    rows = []
    for role, relative in ROLES.items():
        source = ordinary(root / 'preserved-stores' / (role + '.sqlite3'), root)
        active = ordinary(runtime / relative, runtime)
        row = stores[role]
        info = source.stat()
        identity = {'device': info.st_dev, 'inode': info.st_ino}
        if (row['file_identity'] != identity or row['mtime_ns'] != info.st_mtime_ns
                or row['bytes'] != info.st_size or row['integrity_check'] != ['ok']
                or hash_file(source, deadline) != row['sha256']):
            raise ValueError('PRESERVED_STORE_CHANGED_' + role)
        for base in (source, active):
            for suffix in ('-wal', '-shm', '-journal'):
                if ordinary(Path(str(base) + suffix), root).exists():
                    raise ValueError('UNEXPECTED_COMPANION_NO_COPY_' + role)
        active.parent.mkdir(parents=True, exist_ok=True)
        if active.exists():
            if (active.stat().st_dev, active.stat().st_ino) == (info.st_dev, info.st_ino):
                raise ValueError('ACTIVE_LINKED_TO_PRESERVED')
            if hash_file(active, deadline) != row['sha256']:
                raise ValueError('ACTIVE_CHANGED_NO_OVERWRITE_' + role)
        else:
            temporary = ordinary(Path(str(active) + '.preparing'), runtime)
            with temporary.open('xb') as target, source.open('rb') as src:
                while block := src.read(1024 * 1024):
                    if monotonic() >= deadline:
                        raise TimeoutError('COPY_BUDGET_EXHAUSTED')
                    target.write(block)
                target.flush()
                os.fsync(target.fileno())
            if hash_file(temporary, deadline) != row['sha256']:
                raise ValueError('ACTIVE_COPY_HASH_MISMATCH_' + role)
            temporary.rename(active)
        after = source.stat()
        if (after.st_mtime_ns, after.st_size, after.st_ino) != (info.st_mtime_ns, info.st_size, info.st_ino):
            raise ValueError('PRESERVED_CHANGED_DURING_COPY')
        proof_path = out / (role + '-portable-proof.json')
        proof = {'schema': 'KQUANT_PORTABLE_SNAPSHOT_PROOF_V1', 'role': role,
            'database_path': str(source), 'bytes': info.st_size, 'mtime_ns': info.st_mtime_ns,
            'sha256': row['sha256'], 'integrity': ['ok'],
            'verified_at': (json.loads(proof_path.read_text(encoding='utf-8'))['verified_at']
                if proof_path.exists() else datetime.now(UTC).isoformat()),
            'wal_shm': [], 'restore_receipt': ref(restore_path), 'core_sha256': restore['core_sha256'],
            'validated_snapshot': {'path': str(source), 'bytes': info.st_size, 'mtime_ns': info.st_mtime_ns,
                'file_identity': identity, 'integrity': ['ok'], 'wal_shm': []}}
        record(proof_path, proof)
        rows.append({'role': role, 'path': str(active), 'recovery_path': str(source),
            'recovery_state': 'COMPLETE_VERIFIED', 'receipt': ref(proof_path),
            'watermarks': [{'table': m['table'], 'column': m['column']} for m in row['selected_watermarks']]})
    rows.append({'role': 'minute', 'path': str(minute), 'recovery_state': 'NEW_EPOCH_VERIFIED',
                 'watermarks': [{'table': 'data_epoch_boundary', 'column': 'id'}]})
    request['databases'] = rows
    record(out / 'activation-request.json', request)
    result = produce(request, roots=[root])
    result['observed_at'] = datetime.now(UTC).isoformat()
    with (out / ('activation-result-' + datetime.now(UTC).strftime('%H%M%S%f') + '.json')).open('x') as stream:
        json.dump(result, stream, indent=2)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--acceptance', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prepare(args.root, args.review, args.acceptance, args.out, args.execute), indent=2))
