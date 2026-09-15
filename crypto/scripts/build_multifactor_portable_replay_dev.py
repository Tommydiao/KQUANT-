"""Build and actually exercise a source/data-isolated DEV dataset replay bundle."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    'scripts/build_hybrid_multifactor_dev.py',
    'kquant_crypto/__init__.py', 'kquant_crypto/candidate_policy.py',
    'kquant_crypto/hybrid_dataset.py', 'kquant_crypto/hybrid_dataset_capsule.py',
    'kquant_crypto/hybrid_multifactor_dev.py', 'kquant_crypto/hybrid_multifactor_labels.py',
    'kquant_crypto/hybrid_factor_contract.py', 'kquant_crypto/hybrid_trend_features.py',
    'kquant_crypto/hybrid_dependence_features.py', 'kquant_crypto/strategy_dual_mode_v1.py')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(out, capsule, reference, portfolio=False):
    if out.exists():
        raise ValueError('A new portable build directory is required')
    if any(not p.is_relative_to(ROOT/'outputs/hybrid_delivery') for p in (out, capsule, reference)):
        raise ValueError('Independent research paths required')
    definition = json.loads((capsule/'capsule.json').read_text())
    expected = json.loads((reference/'report.json').read_text())
    if definition['dataset_hash'] != expected['dataset_hash']:
        raise ValueError('Reference and capsule dataset mismatch')
    members = list(SOURCES)
    if portfolio:
        members += ['scripts/replay_multifactor_portfolio.py',
            'kquant_crypto/candidate_simulation.py', 'kquant_crypto/hybrid_research_portfolio.py',
            'kquant_crypto/hybrid_exit_research.py', 'kquant_crypto/hybrid_dev_fit.py',
            'config/dual_regime_candidate_v1.json', 'config/hybrid_exit_research_v1.json',
            'docs/KQUANT_24H_Dual_Regime_Strategy_Plan_V2.0.md',
            'outputs/dual_regime_v1/exchange_rules.json']
    contents = {name:(ROOT/name).read_bytes() for name in members}
    contents['data/capsule.json'] = (capsule/'capsule.json').read_bytes()
    for frames in definition['files'].values():
        for entry in frames.values():
            path = (capsule/entry['path']).resolve()
            if path.parent != capsule or sha(path) != entry['sha256']:
                raise ValueError('Capsule member identity mismatch')
            contents['data/'+path.name] = path.read_bytes()
    versions = {'python':sys.version, 'duckdb':importlib.metadata.version('duckdb')}
    contents['requirements.txt'] = ('duckdb=='+versions['duckdb']+'\n').encode()
    contents['RUNBOOK.md'] = (
        '# Authorized DEV Dataset Replay\n\n'
        'This package rebuilds factors/labels only, not the whole research system.\n'
        'Use a separate Python environment; install requirements.txt there.\n'
        'No credentials, network ingestion, trading, model loading or restricted tail are included.\n\n'
        'Run from this directory, using a new output directory for each run:\n\n'
        '```text\npython -I -B scripts/build_hybrid_multifactor_dev.py --capsule data '
        '--output outputs/hybrid_delivery/rebuilt\n```\n\n'
        'Compare dataset_hash/features_hash/labels_hash in the generated report.json '
        'with REPLAY_MANIFEST.json expected_results. Historical availability is assumed close, '
        'not actual quote execution. Profitability and independent OOS remain unproven.\n'
        'The build verification used the recorded existing interpreter, not a fresh dependency install.\n'
    ).encode()
    hashes = {name:hashlib.sha256(raw).hexdigest() for name,raw in contents.items()}
    if portfolio:
        contents['RUNBOOK.md'] = (
            '# Authorized DEV Portfolio Replay\n\n'
            'Frozen A entry policy, ORIGINAL/fixed2.5R/fixed3R/T1/T2 exit comparisons. '
            'No optimization or strategy admission. Results remain exposed research.\n'
            'Create an isolated Python environment and install requirements.txt.\n\n'
            '```text\npython -I -B scripts/replay_multifactor_portfolio.py --capsule data '
            '--output outputs/hybrid_delivery/rebuilt\n```\n\n'
            'Compare report dataset_hash and every scenarios trade_hash/equity_hash '
            'against REPLAY_MANIFEST.json. Generated trades.jsonl/equity.jsonl '
            'remain in each scenario directory. Frozen current exchange filters '
            'are not historical PIT rules. No independent OOS or profit PASS.\n'
            'No account, network ingestion, model activation or order service included.\n'
        ).encode()
        hashes = {name:hashlib.sha256(raw).hexdigest() for name,raw in contents.items()}
    manifest = dict(scope='DEV_ONLY_PORTFOLIO_REPLAY' if portfolio else 'DEV_ONLY_DATASET_REPLAY', execution_enabled=False,
        full_system_release=False, files=hashes, environment=versions,
        expected_results={k:expected[k] for k in (('dataset_hash','scenarios') if portfolio else ('dataset_hash','features_hash','labels_hash'))},
        reference_report_hash=sha(reference/'report.json'),
        limitations=['Source/data isolation tested, fresh dependency installation not tested by builder',
                     'No model fitting, MC or online lifecycle acceptance in this package'])
    contents['REPLAY_MANIFEST.json'] = json.dumps(manifest, sort_keys=True, indent=2).encode()
    out.mkdir(parents=True, exist_ok=False)
    package = out/'package'
    for name,raw in contents.items():
        path = package/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    command = [sys.executable, '-I', '-B', 'scripts/replay_multifactor_portfolio.py' if portfolio else 'scripts/build_hybrid_multifactor_dev.py',
        '--capsule', 'data', '--output', 'outputs/hybrid_delivery/rebuilt']
    started = time.perf_counter()
    completed = subprocess.run(command, cwd=package, capture_output=True, text=True, timeout=600)
    (out/'stdout.txt').write_text(completed.stdout, encoding='utf-8')
    (out/'stderr.txt').write_text(completed.stderr, encoding='utf-8')
    result = dict(command=command, cwd=str(package), exit_code=completed.returncode,
        elapsed_seconds=time.perf_counter()-started, fresh_environment=False)
    if completed.returncode == 0:
        actual = json.loads((package/'outputs/hybrid_delivery/rebuilt/report.json').read_text())
        result['parity'] = {k:actual[k] == v for k,v in manifest['expected_results'].items()}
    result['source_unchanged'] = all(sha(ROOT/name) == hashes[name] for name in members)
    result['packaged_inputs_unchanged'] = all(sha(package/name) == value for name,value in hashes.items())
    passed = (completed.returncode == 0 and all(result['parity'].values())
              and result['source_unchanged'] and result['packaged_inputs_unchanged'])
    result['status'] = 'SOURCE_DATA_ISOLATED_REPLAY_PASS' if passed else 'FAIL'
    if passed:
        archive_path = out/('authorized_dev_portfolio_replay.zip' if portfolio else 'authorized_dev_dataset_replay.zip')
        with zipfile.ZipFile(archive_path, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
            for name,raw in sorted(contents.items()):
                item = zipfile.ZipInfo(name, (1980,1,1,0,0,0))
                item.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(item, raw)
        result['archive_hash'] = sha(archive_path)
        result['archive_bytes'] = archive_path.stat().st_size
    (out/'verification.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ('output','capsule','reference'):
        p.add_argument('--'+name, required=True)
    p.add_argument('--portfolio', action='store_true')
    a = p.parse_args()
    result = build(*[(ROOT/getattr(a,k)).resolve() for k in ('output','capsule','reference')], portfolio=a.portfolio)
    print(json.dumps(result))
    sys.exit(0 if result['status'] == 'SOURCE_DATA_ISOLATED_REPLAY_PASS' else 1)
