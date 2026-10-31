"""Prepare a portable scope; create a new minute store only with real acceptance.

No old-machine paths, date rewrites, activation, SDK, or OWNER records are made.
The session is the immutable epoch start, not a daily expiration of acceptance.
"""
from __future__ import annotations

import argparse
import ast
from datetime import date
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


def ordinary(path: Path, root: Path) -> Path:
    path = path.absolute()
    if path.drive.upper() == 'F:' or not path.is_relative_to(root.absolute()):
        raise ValueError('PATH_OUTSIDE_SAFE_ROOT')
    for parent in [*path.parents, path]:
        if parent.exists() and (parent.is_symlink() or getattr(parent.lstat(), 'st_file_attributes', 0) & 0x400):
            raise ValueError('REPARSE_PATH_FORBIDDEN')
    return path


def engine(root: Path):
    tools = ordinary(root / 'source/development/handoff/tools', root)
    sys.path.insert(0, str(tools))
    spec = importlib.util.spec_from_file_location('portable_new_data_epoch', tools / 'new_data_epoch.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def schema_at(root: Path) -> tuple[str, str]:
    path = ordinary(root / 'source/development/workspace/kquant/options_one_minute.py', root)
    raw = path.read_bytes()
    tree = ast.parse(raw.decode('utf-8-sig'))
    values = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == 'SCHEMA' for t in n.targets)]
    if len(values) != 1 or not isinstance(values[0], str):
        raise ValueError('EXACT_SOURCE_SCHEMA_REQUIRED')
    return values[0], hashlib.sha256(raw).hexdigest()


def proposal(root: Path, session: str, epoch_id: str) -> dict:
    root = ordinary(root.absolute(), root.absolute())
    start = date.fromisoformat(session)
    module = engine(root)
    schema, source_sha = schema_at(root)
    runtime = ordinary(root / 'runtime', root)
    minute = runtime / 'work' / ('options_one_minute-epoch-' + start.strftime('%Y%m%d')) / 'one_minute.sqlite3'
    declaration = {
        'schema': 'KQUANT_NEW_MINUTE_EPOCH_V1', 'runtime_root': str(runtime),
        'minute_path': str(minute), 'session': session, 'epoch_id': epoch_id,
        'schema_sha256': hashlib.sha256(schema.encode()).hexdigest(),
        'preserved_roles': sorted(module.PRESERVED_ROLES),
        'unresolved_old_records': sorted(module.MISSING_RECORDS),
        'old_position_continuity': 'UNKNOWN', 'complete_restoration_claimed': False,
        'execution_enabled': False, 'qualified_signal_authorized': False,
        'session_semantics': 'EPOCH_START_SUBSEQUENT_SESSIONS_SAME_BOUNDARY',
    }
    checked = module.check(declaration, None, roots=[root])
    if checked['errors'] != [{'code': 'EXACT_DATA_SCOPE_ACCEPTANCE_REQUIRED'}]:
        raise ValueError('SCOPE_PREFLIGHT_FAILED: ' + json.dumps(checked['errors']))
    return {'schema': 'KQUANT_LOCAL_EPOCH_REVIEW_V1', 'root': str(root),
            'source_sha256': source_sha, 'declaration': declaration,
            'declaration_sha256': module.declaration_hash(declaration),
            'old_business_continuity': 'UNKNOWN', 'acceptance': None,
            'can_launch': False, 'preflight': checked}


def evaluate(root: Path, review: dict, acceptance: dict | None, *, create=False):
    root = ordinary(root.absolute(), root.absolute())
    if review.get('schema') != 'KQUANT_LOCAL_EPOCH_REVIEW_V1' or review.get('root') != str(root):
        raise ValueError('LOCAL_MACHINE_SCOPE_MISMATCH')
    module = engine(root)
    declaration = review['declaration']
    schema, source_sha = schema_at(root)
    if source_sha != review['source_sha256'] or module.declaration_hash(declaration) != review['declaration_sha256']:
        raise ValueError('LOCAL_REVIEW_OR_SOURCE_CHANGED')
    if declaration['runtime_root'] != str(root / 'runtime'):
        raise ValueError('LOCAL_RUNTIME_SCOPE_MISMATCH')
    ordinary(Path(declaration['minute_path']), root / 'runtime')
    if create:
        return module.initialize(declaration, acceptance, roots=[root], schema=schema, budget_seconds=5)
    return module.check(declaration, acceptance, roots=[root])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--propose', action='store_true')
    parser.add_argument('--start-session')
    parser.add_argument('--epoch-id')
    parser.add_argument('--review', type=Path)
    parser.add_argument('--acceptance', type=Path)
    parser.add_argument('--initialize', action='store_true')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if args.propose:
        if not args.start_session or not args.epoch_id or args.initialize or args.acceptance:
            parser.error('Proposal requires session/epoch and cannot initialize or accept')
        result = proposal(args.root, args.start_session, args.epoch_id)
    else:
        if not args.review or (args.initialize and (not args.acceptance or not args.out)):
            parser.error('Review required; initialization also requires acceptance and a fresh receipt')
        review = json.loads(ordinary(args.review, args.root).read_text(encoding='utf-8-sig'))
        acceptance = (json.loads(ordinary(args.acceptance, args.root).read_text(encoding='utf-8-sig'))
                      if args.acceptance else None)
        if args.out and ordinary(args.out, args.root).exists():
            raise ValueError('RECEIPT_ALREADY_EXISTS_NO_REPEAT_INITIALIZATION')
        result = evaluate(args.root, review, acceptance, create=args.initialize)
    if args.out:
        path = ordinary(args.out, args.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
