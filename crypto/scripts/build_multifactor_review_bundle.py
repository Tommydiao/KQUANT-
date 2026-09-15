"""Package explicit research evidence only, with no credentials or live database."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha, write_json
from verify_multifactor_review_bundle import verify


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    out = (ROOT / parser.parse_args().output).resolve()
    base = ROOT / 'outputs/hybrid_delivery'
    if not out.is_relative_to(base):
        raise ValueError('Independent review output required')
    directories = [
        'multifactor_population_fit_20260908_01', 'multifactor_population_prediction_20260908_01',
        'multifactor_population_chain_audit_20260908_01', 'multifactor_population_20260907_01',
        'multifactor_ablation_20260908_01', 'multifactor_policy_holding_v2_20260908_01',
        'multifactor_sidecar_audit_20260908_02', 'multifactor_mc_audit_20260907_02',
        'multifactor_portfolio_audit_20260907_01', 'multifactor_nested_baseline_20260907_01',
        'multifactor_regression_20260908_01', 'multifactor_math_regression_20260908_01']
    paths = []
    for directory in directories:
        paths.extend(p for p in (base / directory).iterdir()
                     if p.is_file() and p.suffix in {'.json', '.jsonl', '.csv', '.nc', '.xml'})
    portfolio = base / 'multifactor_portfolio_20260907_02'
    paths.append(portfolio / 'report.json')
    for scenario in ('ORIGINAL_1', 'FIXED_2_5R_1', 'FIXED_3R_1', 'T1_1', 'T1_2', 'T2_1', 'T2_2'):
        paths.extend(portfolio / scenario / name for name in ('trades.jsonl', 'equity.jsonl', 'report.json'))
    paths.extend(ROOT / name for name in (
        'scripts/verify_multifactor_review_bundle.py', 'scripts/audit_multifactor_population_prediction_dev.py',
        'scripts/audit_multifactor_completed_chains_dev.py', 'scripts/fit_multifactor_population_dev.py',
        'docs/HYBRID_GPT_REVIEW_REPORT_20260907.md', 'docs/HYBRID_TO_LIVE_RESUME.md',
        'plan/hybrid_multifactor_dev_tasks_v1.json'))
    paths.extend((ROOT / 'kquant_crypto').glob('hybrid*.py'))
    payload = {}
    for path in paths:
        if not path.resolve().is_relative_to(ROOT):
            raise ValueError('Evidence link leaves repository')
        payload[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    hashes = {name: hashlib.sha256(value).hexdigest() for name, value in payload.items()}
    manifest = {'scope': 'DEV_ONLY_REVIEW', 'deployable': False, 'files': hashes,
        'model_numerical_gate': 'FAIL_ONE_DIVERGENCE', 'performance': 'PERFORMANCE_UNPROVEN',
        'limitations': ['No new model calibration or independent OOS',
            'Raw authorized OHLC history and full runtime dependencies remain local; not a standalone replay release',
            'MC path-level source remains local; included MC report is conditional on one snapshot',
            'No credentials, runtime database, formal EVAL or execution configuration bundled'],
        'verification_command': 'python scripts/verify_multifactor_review_bundle.py <archive.zip>'}
    out.mkdir(exist_ok=False)
    payload['MANIFEST.json'] = json.dumps(manifest, sort_keys=True, indent=2).encode()
    target = out / 'KQUANT_MULTIFACTOR_DEV_REVIEW_20260908.zip'
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in sorted(payload.items()):
            item = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(item, value)
    if any(sha(ROOT / name) != digest for name, digest in hashes.items()):
        raise ValueError('Evidence changed during packaging')
    result = {**verify(target), 'archive_sha256': sha(target), 'archive_bytes': target.stat().st_size}
    write_json(out / 'verification.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
