"""Prepare an exact, unaccepted deployment projection without touching live files."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

DEV = Path(__file__).resolve().parents[1]
BASE = DEV.parent / 'workspace'
ROOT = BASE.parents[2]


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=True, indent=2) + '\n').encode()


def save(path, value):
    body = encoded(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != body:
            raise ValueError('PROJECTION_EXISTS_WITH_DIFFERENT_CONTENT')
    else:
        with path.open('xb') as stream:
            stream.write(body)
    return {'path': str(path), 'sha256': sha256(body).hexdigest()}


def prepare():
    entry_path = BASE / 'config/local_workspace_entry.json'
    entry = json.loads(entry_path.read_text())
    old_dir = Path(entry['runtime_manifest']['path']).parent
    release = json.loads(Path(entry['runtime_manifest']['path']).read_text())
    recovery = json.loads((old_dir / 'recovery-manifest.json').read_text())
    if digest(Path(entry['runtime_manifest']['path'])) != entry['runtime_manifest']['sha256']:
        raise ValueError('BASE_MANIFEST_CHANGED')
    replacements = {}
    for folder in ('kquant', 'web/src'):
        for path in sorted((DEV / folder).rglob('*')):
            if path.is_file() and path.suffix in {'.py', '.tsx', '.css'}:
                replacements[path.relative_to(DEV).as_posix()] = path
    for build, target in (('unified', 'dist-unified'), ('stock', 'dist-stock')):
        for path in sorted((DEV / 'build' / build).rglob('*')):
            if path.is_file():
                replacements['web/' + target + '/' + path.relative_to(DEV / 'build' / build).as_posix()] = path
    # Validate the accepted baseline before projecting any replacement.
    for proof in recovery['required_source'] + recovery['frontend']:
        path = Path(proof['path'])
        if not path.is_relative_to(ROOT) or digest(path) != proof['sha256']:
            raise ValueError('ACCEPTED_BASELINE_DRIFT:' + path.name)
    delta = [dict(target=key, payload=str(path), sha256=digest(path),
                  previous_sha256=digest(BASE / key) if (BASE / key).is_file() else None)
             for key, path in sorted(replacements.items())]
    projected = deepcopy(release)
    for row in delta:
        if not row['target'].startswith('web/dist-unified/'):
            projected['files'][row['target']] = {'sha256': row['sha256']}
    for key, prefix in (('frontend_files', 'web/dist-unified/'),
                        ('auxiliary_frontend_files', 'web/dist-stock/')):
        projected[key] = {r['target']: r['sha256'] for r in delta if r['target'].startswith(prefix)}
    # Retired build assets are not required by this candidate, but remain in the
    # explicit rollback base. No live file is removed by projection.
    for key in list(projected['files']):
        if key.startswith('web/dist-stock/') and key not in projected['auxiliary_frontend_files']:
            del projected['files'][key]
    projected.pop('candidate_id', None)
    projected['production_accepted'] = False
    candidate = 'local-candidate-' + sha256(encoded(projected)).hexdigest()[:16]
    projected['candidate_id'] = candidate
    out = DEV / 'release' / candidate
    release_proof = save(out / 'release-manifest.json', projected)
    required = {p['path']: p for p in recovery['required_source']
                if Path(p['path']) != old_dir / 'release-manifest.json'
                and not Path(p['path']).is_relative_to(BASE / 'web/dist-stock')}
    for row in delta:
        if not row['target'].startswith('web/dist-unified/'):
            required[str(BASE / row['target'])] = {'path': str(BASE / row['target']), 'sha256': row['sha256']}
    required[release_proof['path']] = release_proof
    recovery.update(candidate_id=candidate, final_runtime_accepted=False,
                    qualified_signal_authorized=False,
                    required_source=list(required.values()),
                    frontend=[{'path': str(BASE / key), 'sha256': value}
                              for key, value in projected['frontend_files'].items()])
    recovery.pop('acceptance_receipt', None)
    recovery_proof = save(out / 'recovery-manifest.json', recovery)
    proposed_entry = {**entry, 'candidate_id': candidate, 'runtime_manifest': release_proof,
                      'recovery_manifest': recovery_proof, 'production_accepted': False,
                      'shadow_runtime_accepted': False}
    save(out / 'proposed-local-workspace-entry.json', proposed_entry)
    bundle = {'schema': 'KQUANT_UNACCEPTED_RESEARCH_DELTA_V1', 'candidate_id': candidate,
              'base_candidate': entry['candidate_id'], 'base_entry_sha256': digest(entry_path),
              'release_manifest': release_proof, 'recovery_manifest': recovery_proof,
              'changes': delta, 'retired_build_assets': sorted(set(release['frontend_files'])
                  .difference(projected['frontend_files']) | set(release.get('auxiliary_frontend_files', {}))
                  .difference(projected['auxiliary_frontend_files'])),
              'approved': False, 'applied': False, 'production_accepted': False,
              'qualified_signal_authorized': False,
              'deployment_requires': ['exact OWNER research-only acceptance',
                  'original controlled stop with matching process identities',
                  'recheck baseline and delta hashes', 'save changed-file-only rollback payload',
                  'atomic file replacement while stopped', 'original five-role preflight',
                  'bind authentic acceptance and select entry', 'original launch and live observation'],
              'preparation_tool_sha256': digest(Path(__file__))}
    proof = save(out / 'deployment-projection.json', bundle)
    return {**proof, 'candidate_id': candidate, 'changes': len(delta), 'applied': False}


if __name__ == '__main__':
    print(json.dumps(prepare()))
