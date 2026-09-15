"""Deterministic source checkpoint, excluding secrets, data and running services."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha, write_json


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    p.add_argument('--evidence', action='append', required=True)
    args = p.parse_args()
    out = (ROOT / args.output).resolve()
    parent = ROOT / 'outputs/hybrid_delivery'
    if not out.is_relative_to(parent):
        raise ValueError('Independent archive required')
    paths = set()
    for folder in ('kquant_crypto', 'scripts'):
        paths.update((ROOT / folder).rglob('*.py'))
    paths.update((ROOT / 'tests').glob('test_hybrid*.py'))
    paths.update((ROOT / 'tests').glob('test_multifactor*.py'))
    paths.update((ROOT / 'config').glob('hybrid*.json'))
    paths.add(ROOT / 'config/dual_regime_candidate_v1.json')
    paths.add(ROOT / 'plan/hybrid_multifactor_dev_tasks_v1.json')
    paths.add(ROOT / 'docs/HYBRID_TO_LIVE_RESUME.md')
    paths.add(ROOT / 'docs/HYBRID_GPT_REVIEW_REPORT_20260907.md')
    # Never recurse work/, .env, outputs, databases or credentials.
    contents = {path.relative_to(ROOT).as_posix(): path.read_bytes() for path in sorted(paths)}
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in contents.items()}
    evidence = []
    for arg in args.evidence:
        path = (ROOT / arg).resolve()
        if not path.is_relative_to(parent):
            raise ValueError('Research evidence path required')
        config = json.loads(path.read_text())
        expected = {**config.get('source_hashes', {}), **config.get('code_hashes', {})}
        checks = {name: hashes.get(name) == value for name, value in expected.items()}
        if 'code_hash' in config:
            checks['entrypoint_hash_present'] = config['code_hash'] in hashes.values()
        if 'kernel_hash' in config:
            checks['kernel_hash_present'] = config['kernel_hash'] in hashes.values()
        for field in ('source_code_hash', 'grouped_diagnostic_code_hash'):
            if field in config:
                checks[field + '_present'] = config[field] in hashes.values()
        evidence.append({'path': path.relative_to(ROOT).as_posix(), 'sha256': sha(path),
                         'declared_code_checks': checks,
                         'declared_code_available': bool(checks) and all(checks.values())})
        contents['evidence/' + path.parent.name + '/' + path.name] = path.read_bytes()
    out.mkdir(exist_ok=False)
    with zipfile.ZipFile(out / 'source_archive.zip', 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(contents.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    if any(sha(ROOT / name) != digest for name, digest in hashes.items()):
        raise RuntimeError('Source changed while archiving; do not accept checkpoint')
    versions = {}
    for package in ('numpy', 'scipy', 'pymc', 'pytensor', 'arviz', 'duckdb', 'pytest'):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    result = {'scope': 'DEV_ONLY_SOURCE_CHECKPOINT', 'files': hashes, 'evidence': evidence,
              'archive_sha256': sha(out / 'source_archive.zip'), 'interpreter': sys.executable,
              'python': sys.version, 'package_versions': versions,
              'data_embedded': False, 'model_embedded': False, 'deployable_release': False,
              'limits': 'Declared hashes checked; transitive runtime/environment/data reproducibility not fully certified',
              'execution_enabled': False}
    write_json(out / 'archive_manifest.json', result)
    print(json.dumps({'archive_sha256': result['archive_sha256'], 'source_files': len(hashes), 'evidence': evidence}))


if __name__ == '__main__':
    main()
