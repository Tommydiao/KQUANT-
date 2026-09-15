"""Incremental evidence audit; reads only previously authorized development data."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys
from datetime import datetime, UTC

from kquant_crypto.hybrid_delivery import load, sha, atomic_json

FIT = 'outputs/hybrid_regime_v1/dev_fit_20260905_03'
POSTERIOR_HASH = '0ecd5412500f820e96c8629d5a1b2e0d6f3751216c25556b6e457601b131dc61'
CONFIG_HASH = '825e79b614cd3c2edc72dd530cdc143d30f150a47720549f42a122ffd5693f0f'


def verify_frozen_inputs(root):
    root = Path(root).resolve()
    fit = root / FIT
    if sha(fit / 'posterior.nc') != POSTERIOR_HASH or sha(root / 'config/hybrid_dev_fit_v1.json') != CONFIG_HASH:
        raise ValueError('Frozen posterior or statistical policy changed')
    manifest = load(fit / 'delivery_manifest.json')
    checks = {}
    for group in ('output_hashes', 'source_hashes'):
        for relative, digest in manifest[group].items():
            p = (root / relative.replace('\\', '/')).resolve()
            if not p.is_relative_to(root):
                raise ValueError('Unsafe old manifest')
            checks[relative] = p.is_file() and sha(p) == digest
    old = load(root / 'outputs/hybrid_regime_v1/m2_traceability_inventory_20260905_final/baseline_reference_manifest.json')
    for relative in manifest['protected_old_source_checks']:
        expected = old['source_file_hashes'].get(relative)
        if expected is None:
            raise ValueError('Protected baseline reference missing: ' + relative)
        checks['protected:' + relative] = sha(root.parent / relative.replace('\\', '/')) == expected
    if not all(checks.values()):
        raise ValueError('Frozen evidence mismatch: ' + ', '.join(k for k,v in checks.items() if not v))
    # Reuse the audited label contract: no model fit and no holdout reads.
    from kquant_crypto.hybrid_dev_fit import audit
    selected, data = audit(load(root / 'config/hybrid_dev_fit_v1.json'))
    meta = load(fit / 'artifact.json')
    if meta['scope'] != 'DEV_ONLY' or meta['runtime_enabled'] or meta['admission'] != 'ABSTAIN':
        raise ValueError('Old model permission drift')
    checks['mature_27_unfilled_23_no_B'] = len(selected) == 27 and len(data['excluded_unavailable']) == 23 and not data['B185_merged']
    return {'checks': checks, 'baseline_integrity': True, 'development_data_eligible': True,
            'label_audit': data, 'posterior_hash': POSTERIOR_HASH, 'scope': 'DEV_ONLY_EXPOSED_BAR_PROXY',
            'G2_passed': False, 'live_enabled': False}


def run(root, out):
    root, out = Path(root).resolve(), Path(out).resolve()
    if not out.is_relative_to(root / 'outputs/hybrid_delivery'):
        raise ValueError('New independent delivery output required')
    out.mkdir(parents=True, exist_ok=False)
    result = verify_frozen_inputs(root)
    def git(*args):
        return subprocess.run(['git', *args], cwd=root.parent, capture_output=True, check=True).stdout
    result['head'] = git('rev-parse', 'HEAD').decode().strip()
    result['python'] = {'executable': sys.executable, 'version': sys.version, 'module': __file__}
    result['observed_at_raw_local_utc'] = datetime.now(UTC).isoformat()
    diff = git('diff', '--binary', '--no-ext-diff')
    (out / 'tracked_diff.patch').write_bytes(diff)
    (out / 'git_status.txt').write_bytes(git('status', '--short', '--branch'))
    result['tracked_diff_sha256'] = sha(out / 'tracked_diff.patch')
    result['tracked_diff_unchanged'] = result['tracked_diff_sha256'] == '1f250cf2a0a9d3ff59f6e9e0b5adcd5aa1fcfd10d208b33625bf26e338ada6bc'
    if not result['tracked_diff_unchanged']:
        result['baseline_integrity'] = False
    collector = load(root / 'outputs/crypto_collection_latest.json')
    result['collector'] = {k: collector.get(k) for k in ('started_at', 'ended_at', 'requested_hours', 'status')}
    result['collector']['note'] = 'Read ended_at with process inventory; no service manipulation'
    # Filter locally and only output command lines of known public application processes.
    ps = "Get-CimInstance Win32_Process | Where-Object { $_.Name -match 'python' -and $_.CommandLine -match 'run_crypto_collection|run_candidate_simulation|kquant_crypto (serve|gateway)|kquant.dashboard' } | Select-Object ProcessId,ParentProcessId,CreationDate,ExecutablePath,CommandLine | ConvertTo-Json -Depth 3"
    process = subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True)
    (out / 'processes.json').write_bytes(process.stdout)
    result['process_inventory_exit_code'] = process.returncode
    result['process_inventory_sha256'] = sha(out / 'processes.json')
    result['checks']['process_inventory_success'] = process.returncode == 0
    atomic_json(out / 'audit.json', result)
    return result


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    a = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    print(json.dumps(run(root, root / a.output), ensure_ascii=False, indent=2))
