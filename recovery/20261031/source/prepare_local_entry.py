"""Build hash-bound local candidate references, never approvals or business copies."""
import argparse
from hashlib import sha256
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import sys
import tempfile

ROOT = Path(__file__).absolute().parent.parent
CODE = ROOT / 'source/development/workspace'
sys.path.insert(0, str(CODE))
from kquant.recovery_preflight import checked_path, canonical_hash, safe_relative, NEW_EPOCH


def safe(path):
    return checked_path(str(Path(path).absolute()), [ROOT])


def proof(path):
    path = safe(path)
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError('SMALL_ARTIFACT_REQUIRED')
    return {'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest()}


def save(path, value):
    path = safe(path)
    content = json.dumps(value, ensure_ascii=True, indent=2) + '\n'
    if path.exists():
        if path.read_text(encoding='utf-8') != content:
            raise ValueError('EXISTING_CANDIDATE_DIFFERS_NO_OVERWRITE')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8') as handle:
            handle.write(content)
    return proof(path)


def configuration_files():
    pending = [safe(CODE / 'config')]
    result = []
    while pending:
        for child in pending.pop().iterdir():
            child = safe(child)
            if child.is_dir():
                pending.append(child)
            elif child.suffix == '.json' and child.name != 'local_workspace_entry.json':
                result.append(child)
            if len(result) + len(pending) > 1024:
                raise ValueError('CONFIG_INVENTORY_LIMIT')
    return sorted(result)


EXTERNAL_PRODUCTION_TOOLS = (
    'capture_missing_asset_candidates.py', 'declare_unavailable_asset_facts.py',
    'integrate_recaptured_assets.py', 'write_quote_source_review.py',
    'run_quote_facts.py', 'run_watchlist_quote_facts_series.py',
    'probe_market_readiness.py', 'probe_minute_history.py',
    'run_minute_backfill.py', 'run_minute_backfill_series.py', 'minute_rebuild.py',
    'prepare_local_epoch.py', 'prepare_local_runtime.py', 'prepare_portable_activation.py',
    'prepare_candidate_archive.py', 'build_candidate_archive_freeze.py',
    'execute_candidate_packaging.py', 'diagnose_clock_read_only.py', 'verify_sdk_timestamp.py',
)


def external_production_tools():
    paths = [safe(ROOT / 'source' / name) for name in EXTERNAL_PRODUCTION_TOOLS]
    for path in paths:
        if not path.is_file():
            raise ValueError('EXTERNAL_PRODUCTION_TOOL_MISSING:' + path.name)
    return paths


def built_frontends():
    result = {}
    for name, entry in (('dist-unified', 'unified.html'), ('dist-stock', 'index.html')):
        root = safe(CODE / 'web' / name)
        if not safe(root / entry).is_file():
            raise ValueError('BUILT_FRONTEND_REQUIRED:' + name)
        pending, files = [root], []
        while pending:
            for child in pending.pop().iterdir():
                child = safe(child)
                if child.is_dir():
                    pending.append(child)
                else:
                    files.append(child)
                if len(files) + len(pending) > 256:
                    raise ValueError('FRONTEND_INVENTORY_LIMIT')
        result[name] = [proof(path) for path in sorted(files)]
    return result


def source_inventory(configs):
    result = {}
    issues = []
    def visit(value, config, pointer=''):
        if isinstance(value, list):
            for index, row in enumerate(value):
                visit(row, config, pointer + '/' + str(index))
        elif isinstance(value, dict):
            if 'source_path' in value:
                try:
                    relative = safe_relative(value['source_path'])
                    if value.get('status') == 'UNAVAILABLE':
                        parts = pointer.split('/')
                        if (config != CODE / 'config/review_acceptances/options_opening_trend_reference_sources.json'
                                or len(parts) != 3 or parts[1] != 'instrument_facts'
                                or value.get('underlying') != parts[2].replace('~1', '/').replace('~0', '~')
                                or value.get('unavailable_reason') not in {'SOURCE_ORIGINAL_MISSING', 'ASSET_CLASS_REVIEW_REQUIRED', 'SOURCE_IDENTITY_UNCONFIRMED'}
                                or not isinstance(value.get('source_sha256'), str)
                                or len(value['source_sha256']) != 64
                                or any(c not in '0123456789abcdef' for c in value['source_sha256'])):
                            raise ValueError('UNAVAILABLE_DECLARATION_INVALID')
                        safe(CODE / relative)
                        issues.append({'source_path': value['source_path'], 'config_path': str(config.relative_to(CODE)),
                                       'json_pointer': pointer, 'expected_sha256': value['source_sha256'],
                                       'code': 'DECLARED_ASSET_UNAVAILABLE', 'reason': value['unavailable_reason']})
                        return
                    row = proof(CODE / relative)
                    expected = value.get('source_sha256')
                    if not isinstance(expected, str) or row['sha256'] != expected:
                        raise ValueError('SOURCE_PROOF_HASH_MISMATCH')
                    result[row['path']] = row
                except (ValueError, OSError) as exc:
                    issues.append({'source_path': value['source_path'],
                                   'config_path': str(config.relative_to(CODE)),
                                   'json_pointer': pointer,
                                   'expected_sha256': value.get('source_sha256'),
                                   'code': str(exc) if isinstance(exc, ValueError) else type(exc).__name__})
                if len(result) > 1024:
                    raise ValueError('SOURCE_PROOF_LIMIT')
            for key, nested in value.items():
                token = str(key).replace('~', '~0').replace('/', '~1')
                visit(nested, config, pointer + '/' + token)
    for config in configs:
        proof(config)
        visit(json.loads(config.read_text(encoding='utf-8-sig')), config)
    return [result[key] for key in sorted(result)], issues


def source_proofs(configs):
    facts, issues = source_inventory(configs)
    issues = [row for row in issues if row['code'] != 'DECLARED_ASSET_UNAVAILABLE']
    if issues:
        first = issues[0]
        if first['code'] == 'FileNotFoundError':
            raise FileNotFoundError(first['source_path'])
        raise ValueError(first['code'] + ':' + first['source_path'])
    return facts


def select_entry(path, value, expected_sha256=None):
    path = safe(path)
    if not path.exists():
        if expected_sha256:
            raise ValueError('EXPECTED_ENTRY_MISSING')
        return save(path, value)
    lock = safe(path.with_suffix('.lock'))
    with lock.open('x'):
        pass
    temporary = None
    try:
        old_bytes = path.read_bytes()
        old = json.loads(old_bytes)
        if old == value:
            return proof(path)
        old_hash = sha256(old_bytes).hexdigest()
        if old_hash != expected_sha256:
            raise ValueError('ENTRY_COMPARE_AND_SWAP_REQUIRED')
        if old.get('production_accepted') is not False:
            raise ValueError('ACCEPTED_ENTRY_REQUIRES_RELEASE_WORKFLOW')
        recovery = old['recovery_manifest']
        if proof(recovery['path'])['sha256'] != recovery['sha256']:
            raise ValueError('OLD_RECOVERY_HASH_MISMATCH')
        if json.loads(safe(recovery['path']).read_text(encoding='utf-8'))['final_runtime_accepted'] is not False:
            raise ValueError('ACCEPTED_ENTRY_REQUIRES_RELEASE_WORKFLOW')
        save(ROOT / 'runtime/releases/entry-history' / (old_hash + '.json'), old)
        descriptor, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=True, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        if sha256(path.read_bytes()).hexdigest() != old_hash:
            raise ValueError('ENTRY_CHANGED_DURING_SELECTION')
        os.replace(temporary, path)
        return proof(path)
    finally:
        if temporary and Path(temporary).exists():
            safe(temporary).unlink()
        lock.unlink()


def prepare(materials_path, write=False, expected_entry_sha256=None, stage_only=False):
    materials_proof = proof(materials_path)
    material = json.loads(safe(materials_path).read_text(encoding='utf-8'))
    if material['runtime_root'] != str(ROOT / 'runtime') or material['final_runtime_accepted'] is not False:
        raise ValueError('UNACCEPTED_LOCAL_MATERIALS_REQUIRED')
    if Path(sys.executable) != ROOT / '.venv/Scripts/python.exe':
        raise ValueError('PINNED_LOCAL_INTERPRETER_REQUIRED')
    files = set()
    for folder in ('kquant', 'scripts', 'crypto/kquant_crypto'):
        for path in (CODE / folder).rglob('*'):
            if path.suffix in {'.py', '.ps1'} and '__pycache__' not in path.parts:
                files.add(safe(path))
    for name in ('start_kquant_workspace.ps1', 'pyproject.toml', 'crypto/pyproject.toml'):
        if (CODE / name).is_file():
            files.add(safe(CODE / name))
    configs = configuration_files()
    files.update(configs)
    files.update(external_production_tools())
    facts, issues = source_inventory(configs)
    files.update(Path(row['path']) for row in facts)
    builds = built_frontends()
    # The auxiliary build is bound but does not replace the served unified entry.
    files.update(Path(row['path']) for row in builds['dist-stock'])
    source = [proof(path) for path in sorted(files)]
    source.extend([proof(ROOT / 'Start-Local-KQUANT.ps1'), proof(Path(__file__)),
                   proof(ROOT / '.venv/pyvenv.cfg')])
    frontend = builds['dist-unified']
    versions = {name: version(name) for name in ('longbridge', 'fastapi', 'uvicorn', 'httpx', 'starlette', 'anyio')}
    if versions['longbridge'] != '4.4.1' or platform.python_version() != '3.12.10':
        raise ValueError('PINNED_ENVIRONMENT_CHANGED')
    base = Path(sys.base_prefix)
    checked_path(str(base), [Path.home()])
    active = [str(Path(sys.executable)), str(ROOT / '.venv/Lib/site-packages'), str(base)]
    identity = canonical_hash({'source': source, 'frontend': frontend, 'versions': versions,
                               'materials': materials_proof})[:16]
    out = ROOT / 'runtime/releases' / ('local-candidate-' + identity)
    result = {'candidate_id': out.name, 'directory': str(out), 'source_files': len(source),
              'frontend_files': len(frontend), 'source_proofs': len(facts),
              'frontend_build_files': {name: len(rows) for name, rows in builds.items()},
              'source_issues': issues, 'can_launch': False, 'write': write}
    if not write:
        return result
    if any(row['code'] != 'DECLARED_ASSET_UNAVAILABLE' for row in issues):
        raise ValueError('SOURCE_PROOFS_INCOMPLETE_RUN_PREVIEW')
    dependencies = {'status': 'VERIFIED', 'versions': {**versions, 'python': platform.python_version()},
                    'active_paths': active, 'verification': 'LOCAL_METADATA_AND_PINNED_INTERPRETER_NOT_LIVE_SDK'}
    dep = save(out / 'dependencies.json', dependencies)
    relative = lambda row: Path(row['path']).relative_to(CODE).as_posix()
    release = {'candidate_id': out.name, 'files': {relative(r): {'sha256': r['sha256']} for r in source if Path(r['path']).is_relative_to(CODE)},
               'frontend': str(CODE / 'web/dist-unified'),
               'frontend_files': {relative(r): r['sha256'] for r in frontend},
               'auxiliary_frontend_files': {relative(r): r['sha256'] for r in builds['dist-stock']},
               'dependency_versions': versions, 'production_accepted': False,
               'unavailable_source_facts': [row for row in issues if row['code'] == 'DECLARED_ASSET_UNAVAILABLE'],
               'source_fact_hashes': {relative(r): r['sha256'] for r in facts}}
    release_proof = save(out / 'release-manifest.json', release)
    manifest = {**material, 'schema': NEW_EPOCH, 'candidate_id': out.name,
                'code_root': str(CODE), 'python_executable': str(Path(sys.executable)),
                'required_source': source + [release_proof], 'frontend': frontend,
                'dependencies': {'verified_versions': dependencies['versions'], 'active_paths': active, 'receipt': dep},
                'final_runtime_accepted': False, 'qualified_signal_authorized': False}
    recovery = save(out / 'recovery-manifest.json', manifest)
    entry = {'schema': 'KQUANT_LOCAL_WORKSPACE_ENTRY_V1', 'candidate_id': out.name,
             'code_root': str(CODE), 'runtime_root': str(ROOT / 'runtime'),
             'python_executable': str(Path(sys.executable)), 'python_base_root': str(base),
             'frontend': release['frontend'], 'recovery_manifest': recovery,
             'runtime_manifest': release_proof, 'production_accepted': False}
    result['entry'] = (save(out / 'proposed-local-workspace-entry.json', entry) if stage_only else
                       select_entry(CODE / 'config/local_workspace_entry.json', entry, expected_entry_sha256))
    result['selected'] = not stage_only
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--materials', type=Path, required=True)
    parser.add_argument('--write', action='store_true')
    parser.add_argument('--expected-entry-sha256')
    parser.add_argument('--stage-only', action='store_true', help='Archive a proposal without replacing an accepted entry')
    args = parser.parse_args()
    print(json.dumps(prepare(args.materials, args.write, args.expected_entry_sha256, args.stage_only), ensure_ascii=True))
