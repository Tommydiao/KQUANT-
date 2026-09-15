"""Create an immutable local source recovery bundle, never a deployment."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args])


def eligible(name):
    parts = Path(name).parts
    forbidden = {'work', 'outputs', 'node_modules', '__pycache__', '.git', 'data'}
    filename = Path(name).name.lower()
    environment_secret = filename == '.env' or (filename.startswith('.env.') and filename != '.env.example')
    return not (set(parts) & forbidden or any(p.startswith('.venv') for p in parts)
                or environment_secret or Path(name).suffix.lower() in {'.pem', '.key', '.sqlite3', '.sqlite', '.db', '.p12', '.pfx'}
                or filename.endswith(('.sqlite3-wal', '.sqlite3-shm', '.db-wal', '.db-shm')))


def inspect(root):
    names = sorted(set(git(root, 'ls-files', '-z', '--cached', '--others',
                           '--exclude-standard').decode().split('\0')) - {''})
    rows, excluded = [], []
    for name in names:
        path = root / name
        if not eligible(name):
            excluded.append(name)
            continue
        if not path.exists():
            continue  # Deletions remain represented in the review patch.
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Unsafe source path: ' + name)
        if path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError('Large source requires classification: ' + name)
        data = path.read_bytes()
        # Deliberately bounded checks, not a claim to detect every secret.
        if re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', data):
            raise ValueError('Private key material: ' + name)
        if re.search(rb'(?:ghp_[A-Za-z0-9]{30,}|sk-proj-[A-Za-z0-9_-]{40,})', data):
            raise ValueError('Credential-shaped material: ' + name)
        rows.append({'path': name, 'bytes': len(data),
                     'sha256': hashlib.sha256(data).hexdigest()})
    return rows, excluded


def archive(root, output):
    root = root.resolve()
    rows, excluded = inspect(root)
    head = git(root, 'rev-parse', 'HEAD').decode().strip()
    changed = [n for n in git(root, 'diff', '--name-only', '-z', 'HEAD').decode().split('\0') if n and eligible(n)]
    patch = b''.join(git(root, 'diff', '--binary', 'HEAD', '--', n) for n in changed)
    if re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|ghp_[A-Za-z0-9]{30,}|sk-proj-[A-Za-z0-9_-]{40,}', patch):
        raise ValueError('Credential-shaped material in review patch')
    status = git(root, 'status', '--porcelain=v1', '-z')
    output.mkdir(parents=True, exist_ok=False)
    bundle = output / 'source.zip'
    with zipfile.ZipFile(bundle, 'w', zipfile.ZIP_DEFLATED) as z:
        for row in rows:
            data = (root / row['path']).read_bytes()
            if hashlib.sha256(data).hexdigest() != row['sha256']:
                raise ValueError('Concurrent source modification')
            z.writestr(row['path'], data)
    # Recovery is deliberately isolated and has no runnable secrets or databases.
    restored = output / 'restored'
    restored.mkdir()
    with zipfile.ZipFile(bundle) as z:
        for row in rows:
            target = restored / row['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(row['path']))
            if hashlib.sha256(target.read_bytes()).hexdigest() != row['sha256']:
                raise ValueError('Restore hash mismatch')
    if rows != inspect(root)[0] or head != git(root, 'rev-parse', 'HEAD').decode().strip():
        raise ValueError('Worktree changed while archiving')
    (output / 'review.patch').write_bytes(patch)
    (output / 'git-status.nul').write_bytes(status)
    report = {'head': head, 'files': rows, 'excluded': excluded,
              'source_zip_sha256': hashlib.sha256(bundle.read_bytes()).hexdigest(),
              'source_restore_hashes_pass': True,
              'dependency_install_verified': False, 'runtime_artifacts_restored': False,
              'secret_scan_scope': 'path exclusions and private-key/token signatures only',
              'publish_approved': False, 'execution_enabled': False}
    (output / 'manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'files'}))
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    args = p.parse_args()
    archive(Path(__file__).resolve().parents[2], Path(args.output).resolve())
