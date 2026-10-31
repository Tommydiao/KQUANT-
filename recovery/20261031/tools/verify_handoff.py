"""Offline integrity and syntax checks; no runtime imports, DB or network access."""
import ast
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tokenize

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--git-index', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    records = json.loads((ROOT/'HANDOFF_FILES.json').read_text(encoding='utf-8'))
    failures, syntax, redacted = [], 0, 0
    for row in records:
        path = ROOT/row['path']
        if not path.resolve().is_relative_to(ROOT):
            failures.append({'path':row['path'],'error':'outside_handoff'})
            continue
        if not path.is_file():
            failures.append({'path':row['path'],'error':'missing'})
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != row['export_sha256']:
            failures.append({'path':row['path'],'error':'hash_mismatch'})
        if path.suffix == '.py':
            try:
                with tokenize.open(path) as handle:
                    ast.parse(handle.read(), filename=row['path'])
                syntax += 1
            except (SyntaxError, UnicodeError) as exc:
                failures.append({'path':row['path'],'error':type(exc).__name__})
        redacted += bool(row['redactions'])
    staged = None
    if args.git_index:
        git_root = Path(subprocess.check_output(['git','rev-parse','--show-toplevel'],cwd=ROOT,text=True).strip())
        prefix = ROOT.relative_to(git_root).as_posix()+'/'
        indexed = subprocess.check_output(['git','ls-files','-z','--',prefix],cwd=git_root).decode().split('\0')
        indexed = [name for name in indexed if name]
        expected = {prefix+r['path']:r['export_sha256'] for r in records}
        failures.extend({'path':name,'error':'not_staged'} for name in expected.keys()-set(indexed))
        for name in indexed:
            if re.search(r'(?i)(?:\.(?:sqlite3?|db)(?:-wal|-shm)?$|\.dpapi$|/node_modules/|/__pycache__/|/\.env(?:\.|$)|\.pem$|\.key$)',name):
                failures.append({'path':name,'error':'forbidden_export_path'})
        payload = ''.join(':'+name+'\n' for name in indexed).encode()
        blobs = subprocess.check_output(['git','cat-file','--batch'],input=payload,cwd=git_root)
        stream = io.BytesIO(blobs)
        for name in indexed:
            header = stream.readline().split()
            if len(header) != 3 or header[1] != b'blob':
                raise RuntimeError('Invalid indexed blob header')
            content = stream.read(int(header[2]))
            assert stream.read(1) == b'\n'
            if name in expected and hashlib.sha256(content).hexdigest() != expected[name]:
                failures.append({'path':name,'error':'indexed_hash_mismatch'})
        staged = len(indexed)
    result = {'scope':'OFFLINE_CODE_HANDOFF_ONLY','files':len(records),
              'python_syntax_checked':syntax,'redacted_files':redacted,
              'staged_files_checked':staged,
              'failures':failures,'production_start':False,'business_database_read':False}
    if args.report:
        args.report.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))
    return bool(failures)


if __name__ == '__main__':
    sys.exit(main())
