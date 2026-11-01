"""Read-only source mapping; never starts workers or opens business databases."""
import ast
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parents[1]
FIRST = HERE.parent / 'opening-first-hour'
MONDAY = HERE.parent / 'monday-signal-llm'
ROOT = HERE.parents[4]
BASE = ROOT / 'source/development/workspace'


def proof(path):
    path = path.resolve()
    if not path.is_relative_to(ROOT) or path.drive.upper() == 'F:':
        raise ValueError('SOURCE_OUTSIDE_APPROVED_ROOT')
    return dict(path=str(path.relative_to(ROOT)).replace('\\', '/'),
                sha256=sha256(path.read_bytes()).hexdigest())


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='iteration-unified-source-map-20261101.json')
    args = parser.parse_args()
    projection = MONDAY / 'release/local-candidate-7896a20b9c18c711/deployment-projection.json'
    os.environ['KQUANT_TEST_FROZEN_PROJECTION'] = str(projection)
    os.environ['KQUANT_TEST_WEEKEND_OVERLAY'] = str(HERE)
    sys.path.insert(0, str(FIRST / 'assembly'))
    import bootstrap
    bootstrap.activate()
    import kquant
    import kquant_crypto
    mapping = {}
    for package, directories in (('kquant', kquant.__path__), ('crypto/kquant_crypto', kquant_crypto.__path__)):
        for directory in directories:
            source_root = Path(directory)
            for path in sorted(source_root.rglob('*.py')):
                if '__pycache__' in path.parts:
                    continue
                target = package + '/' + path.relative_to(source_root).as_posix()
                mapping.setdefault(target, path)
    for finder in sys.meta_path:
        if isinstance(finder, bootstrap.FirstHourFinder):
            for module, path in finder.mapping.items():
                target = module.replace('.', '/') + '.py'
                if target.startswith('kquant_crypto/'):
                    target = 'crypto/' + target
                mapping[target] = path
    helpers = {path.stem: path for path in FIRST.glob('*.py') if not path.name.startswith('test_')}
    pending = list(mapping.values())
    examined = set()
    blockers = []
    while pending:
        path = pending.pop()
        if path in examined:
            continue
        examined.add(path)
        tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [item.name for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or '']
            else:
                continue
            for name in names:
                root = name.split('.')[0]
                if root in helpers:
                    target = root + '.py'
                    if target not in mapping:
                        mapping[target] = helpers[root]
                        pending.append(helpers[root])
                if name == 'assembly' or name.startswith('assembly.'):
                    blockers.append(dict(source=proof(path), line=node.lineno,
                                         kind='RUNTIME_IMPORTS_TEST_ASSEMBLY', module=name))
    sources = [dict(target=target, source=proof(path), differs_from_accepted=(
        not (BASE / target).is_file() or sha256((BASE / target).read_bytes()).hexdigest()
        != sha256(path.read_bytes()).hexdigest())) for target, path in sorted(mapping.items())]
    artifact = dict(schema='KQUANT_UNIFIED_SOURCE_MAPPING_DRAFT_V1',
        observed_at=datetime.now(timezone.utc).isoformat(), accepted_entry=proof(BASE/'config/local_workspace_entry.json'),
        parent_projection=proof(projection), sources=sources, blockers=blockers,
        deployment_ready=False, accepted=False, business_database_opened=False,
        limitation='Static module selection and AST dependencies only; not an executable release manifest or approval.')
    target = HERE / 'evidence' / args.output
    target.write_text(json.dumps(artifact, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(path=str(target), sources=len(sources),
        changed=sum(row['differs_from_accepted'] for row in sources),
        assembly_dependencies=len(blockers), deployment_ready=False)))


if __name__ == '__main__':
    main()
