"""Verify a trusted locally built archive, extract safely, and reproduce results."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys
import time
import zipfile


def verify(archive_path, expected_sha, out):
    if out.exists():
        raise ValueError('New verification directory required')
    if hashlib.sha256(archive_path.read_bytes()).hexdigest() != expected_sha:
        raise ValueError('Archive identity mismatch')
    with zipfile.ZipFile(archive_path) as z:
        names = z.namelist()
        if len(names) != len(set(names)) or sum(i.file_size for i in z.infolist()) > 128*1024*1024:
            raise ValueError('Duplicate or oversized members')
        manifest = json.loads(z.read('REPLAY_MANIFEST.json'))
        if manifest['scope'] not in ('DEV_ONLY_DATASET_REPLAY', 'DEV_ONLY_PORTFOLIO_REPLAY') or manifest['execution_enabled'] is not False:
            raise ValueError('Unsupported replay scope')
        for name in set(names) | set(manifest['files']):
            path = PurePosixPath(name)
            if (path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name
                or path.as_posix() != name):
                raise ValueError('Unsafe member path')
        if len({name.casefold() for name in names}) != len(names):
            raise ValueError('Case-aliased member path')
        if set(names) != set(manifest['files']) | {'REPLAY_MANIFEST.json'}:
            raise ValueError('Unexpected/missing archive member')
        contents = {}
        for name in names:
            raw = z.read(name)
            if name != 'REPLAY_MANIFEST.json' and hashlib.sha256(raw).hexdigest() != manifest['files'][name]:
                raise ValueError('Member integrity mismatch')
            contents[name] = raw
    if importlib.metadata.version('duckdb') != manifest['environment']['duckdb']:
        raise ValueError('DuckDB dependency differs')
    if sys.version != manifest['environment']['python']:
        raise ValueError('Python runtime differs from recorded build')
    out.mkdir(parents=True, exist_ok=False)
    package = out/'extracted'
    for name, raw in contents.items():
        path = package/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    entrypoint = 'scripts/replay_multifactor_portfolio.py' if manifest['scope'] == 'DEV_ONLY_PORTFOLIO_REPLAY' else 'scripts/build_hybrid_multifactor_dev.py'
    command = [sys.executable, '-I', '-B', entrypoint,
        '--capsule','data','--output','outputs/hybrid_delivery/rebuilt']
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=package, text=True, capture_output=True, timeout=600)
    (out/'stdout.txt').write_text(completed.stdout, encoding='utf-8')
    (out/'stderr.txt').write_text(completed.stderr, encoding='utf-8')
    result = dict(scope='DEV_ONLY_ARCHIVE_REPRODUCTION', archive_sha256=expected_sha,
        verifier_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        interpreter=sys.executable, prefix=sys.prefix, base_prefix=sys.base_prefix,
        installed_packages={d.metadata['Name']:d.version for d in importlib.metadata.distributions()},
        command=command, exit_code=completed.returncode, elapsed_seconds=time.perf_counter()-started,
        execution_enabled=False, full_system_acceptance=False)
    if completed.returncode == 0:
        report = json.loads((package/'outputs/hybrid_delivery/rebuilt/report.json').read_text())
        result['parity'] = {k:report[k] == value for k,value in manifest['expected_results'].items()}
    result['inputs_unchanged'] = all(hashlib.sha256((package/name).read_bytes()).hexdigest() == value
        for name,value in manifest['files'].items())
    result['status'] = 'PASS' if completed.returncode == 0 and all(result['parity'].values()) and result['inputs_unchanged'] else 'FAIL'
    (out/'verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description='Only run archives whose source you have reviewed and trust.')
    p.add_argument('--archive', required=True)
    p.add_argument('--sha256', required=True)
    p.add_argument('--output', required=True)
    a = p.parse_args()
    result = verify(Path(a.archive).resolve(), a.sha256, Path(a.output).resolve())
    print(json.dumps(result))
    sys.exit(0 if result['status'] == 'PASS' else 1)
