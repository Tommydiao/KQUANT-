"""Read-only M0 inventory. Writes a new audit directory, never existing evidence."""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO, text=True, encoding='utf-8')


def audit(output):
    output = Path(output).resolve()
    allowed = (ROOT / 'outputs' / 'hybrid_regime_v1').resolve()
    if not output.is_relative_to(allowed) or output == allowed:
        raise ValueError('Audit output must be a new child of outputs/hybrid_regime_v1')
    output.mkdir(parents=True, exist_ok=False)
    files = list((ROOT / 'docs').rglob('*.md'))
    names = ['strategy_dual_mode_v1.py', 'candidate_simulation.py', 'candidate_forward.py',
             'candidate_dataset.py', 'candidate_metrics.py', 'candidate_simulation_store.py',
             'candidate_policy.py', 'bayesian_model.py', 'monte_carlo.py', 'llm_advisor.py',
             'evidence_pipeline.py', 'model_registry.py', 'model_baselines.py', 'quantile_model.py']
    files += [ROOT / 'kquant_crypto' / name for name in names]
    files += [ROOT / 'scripts' / 'run_candidate_simulation.py', ROOT / 'config' / 'dual_regime_candidate_v1.json']
    files += list((ROOT/'kquant_crypto').glob('hybrid_*.py'))
    files += list((ROOT/'tests').glob('test_hybrid_*.py'))
    files += [ROOT/'config/hybrid_contract_v1_1.json',Path(__file__),ROOT/'scripts/verify_hybrid_baseline.py']
    frozen = ROOT / 'outputs' / 'dual_regime_v1'
    files += [frozen / 'candidate_selection.json', frozen / 'frozen' / 'data_manifest.json', frozen / 'exchange_rules.json']
    hashes = {str(p.relative_to(REPO)): sha(p) if p.exists() else None for p in files}
    references = {}
    db_path = ROOT / 'work' / 'candidate_simulation.sqlite3'
    with sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        for run in ('dev_A_base_v4', 'dev_B_base_v4', 'forward_A_frozen_v1'):
            row = db.execute('SELECT run_id,metadata,status,created_at,updated_at FROM candidate_runs WHERE run_id=?', (run,)).fetchone()
            if row is None:
                references[run] = {'missing': True}
                continue
            record = dict(row)
            record['metadata'] = json.loads(record['metadata'])
            record['record_counts'] = dict(db.execute('SELECT kind,count(*) FROM candidate_records WHERE run_id=? GROUP BY kind', (run,)))
            lease = db.execute('SELECT owner,expires_at FROM candidate_locks WHERE run_id=?', (run,)).fetchone()
            record['lease'] = None if lease is None else {'owner_hash': hashlib.sha256(lease['owner'].encode()).hexdigest(),
                                                         'expires_at': lease['expires_at'], 'unexpired_at_read': lease['expires_at'] > time.time()}
            references[run] = record
    payload = {'schema': 'hybrid_m0_audit_v1', 'observed_at': datetime.now(timezone.utc).isoformat(),
               'head': git('rev-parse', 'HEAD').strip(), 'status': git('status', '--short'),
               'python': sys.executable, 'python_version': sys.version, 'source_file_hashes': hashes,
               'baseline_references': references, 'market_rows_read': False,
               'existing_database_mode': 'ro/query_only', 'mathematical_filtering_enabled': False,
               'source_hashes_are_not_behavioral_reproduction': True}
    payload['module_origin']=importlib.util.find_spec('kquant_crypto').origin
    payload['cwd_module_origin']=subprocess.check_output(
        [sys.executable,'-c','import kquant_crypto; print(kquant_crypto.__file__)'],
        cwd=ROOT,text=True,encoding='utf-8').strip()
    payload['module_resolution_conflict']=payload['module_origin']!=payload['cwd_module_origin']
    payload['installed_versions']={name:importlib.metadata.version(name) for name in ('pytest','duckdb','pyarrow','numpy')}
    (output / 'baseline_reference_manifest.json').write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
    (output / 'tracked_diff.patch').write_text(git('diff', '--no-ext-diff'), encoding='utf-8')
    print(json.dumps({'output': str(output), 'head': payload['head'], 'files_hashed': len(hashes),
                      'runs': {k: {'status': v.get('status'), 'lease': v.get('lease')} for k, v in references.items()}}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    audit(args.output)
