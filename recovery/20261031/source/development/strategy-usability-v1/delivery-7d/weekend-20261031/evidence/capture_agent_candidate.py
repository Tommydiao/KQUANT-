"""Content-bound development inventory; never applies files or grants launch."""
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[4]
FIRST = HERE.parent/'opening-first-hour'
BASE = ROOT/'source/development/workspace'


def proof(path):
    path = path.resolve()
    if not path.is_relative_to(ROOT) or path.drive.upper() == 'F:':
        raise ValueError('CANDIDATE_PATH_OUTSIDE_PROJECT')
    return dict(path=path.relative_to(ROOT).as_posix(), sha256=sha256(path.read_bytes()).hexdigest())


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--mapping', default='agent-source-map-20261101.json')
    args = parser.parse_args()
    if Path(args.mapping).name != args.mapping:
        raise ValueError('LOCAL_SOURCE_MAP_FILENAME_REQUIRED')
    mapping_path = HERE/'evidence'/args.mapping
    mapping = json.loads(mapping_path.read_text())
    if mapping['blockers']:
        raise ValueError('RUNTIME_TEST_LOADER_DEPENDENCY')
    sources = mapping['sources']
    for item in sources:
        if proof(ROOT/item['source']['path']) != item['source']:
            raise ValueError('CANDIDATE_SOURCE_DRIFT')
    entry_path = BASE/'config/local_workspace_entry.json'
    entry = json.loads(entry_path.read_text(encoding='utf-8-sig'))
    parents = []
    for key in ('runtime_manifest', 'recovery_manifest'):
        actual = proof(Path(entry[key]['path']))
        if actual['sha256'] != entry[key]['sha256']:
            raise ValueError('ACCEPTED_MANIFEST_DRIFT')
        parents.append(actual)
    configuration = proof(HERE/'config/agent_iteration.json')
    builds = [proof(p) for p in sorted((FIRST/'build').rglob('*')) if p.is_file()]
    frontend_sources = [proof(p) for p in sorted((FIRST/'patches/web').rglob('*')) if p.is_file()]
    lifecycle = [dict(target=name, source=proof(FIRST/'lifecycle-candidate'/name))
                 for name in ('start_kquant_workspace.ps1', 'scripts/FoundationLifecycle.ps1')]
    material = dict(sources=sources, builds=builds, frontend_sources=frontend_sources,
                    lifecycle=lifecycle, configuration=configuration, accepted_parent_manifests=parents)
    identity = sha256(json.dumps(material, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    result = dict(schema='KQUANT_AGENT_DEVELOPMENT_CANDIDATE_V1', observed_at=datetime.now(UTC).isoformat(),
        candidate_id='agent-development-'+identity[:16], payload_sha256=identity,
        accepted_entry=proof(entry_path), accepted_candidate_id=entry['candidate_id'], **material,
        launch_accepted=False, can_launch=False, source_map=proof(mapping_path),
        paid_calls_enabled=False, orders_enabled=False, applied=False,
        remaining_gates=['PER_CHECKPOINT_PERFORMANCE', 'TWO_MATCHED_SHORTS', 'MATCHED_HOUR',
            'EXECUTABLE_RELEASE_AND_RECOVERY_MANIFEST', 'EXACT_LAUNCH_ACCEPTANCE', 'BUDGET_ACCEPTANCE'])
    target = HERE/'evidence'/('agent-development-candidate-'+identity[:16]+'.json')
    if target.exists():
        old = json.loads(target.read_text())
        if old['payload_sha256'] != identity:
            raise ValueError('EXISTING_CANDIDATE_CONFLICT')
    else:
        target.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(dict(path=str(target), candidate_id=result['candidate_id'],
        payload_sha256=identity, sources=len(sources), builds=len(builds), can_launch=False)))


if __name__ == '__main__':
    main()
