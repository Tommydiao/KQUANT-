"""Run preregistered ablations without reading diagnostic or restricted labels."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha, write_json
from kquant_crypto.hybrid_factor_ablation import FEATURES, train_ablation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--fit', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    fit, out = [(ROOT / value).resolve() for value in (args.fit, args.output)]
    parent = ROOT / 'outputs/hybrid_delivery'
    if not fit.is_relative_to(parent) or not out.is_relative_to(parent):
        raise ValueError('Independent DEV paths required')
    checkpoint = parent / 'multifactor_pause_20260907_01/checkpoint.json'
    audit = json.loads(checkpoint.read_text())
    if fit != (ROOT / audit['fit_path']).resolve():
        raise ValueError('Only previously frozen training rows authorized')
    if sha(fit / 'training_rows.json') != audit['fit_files']['training_rows.json']:
        raise ValueError('Frozen training hash mismatch')
    out.mkdir(exist_ok=False)
    write_json(out / 'preregistration.json', {
        'scope': 'DEV_ONLY', 'exposure': 'EXPOSED_RESEARCH', 'alpha': 1.0,
        'feature_order': list(FEATURES), 'variants': 'FULL plus each one removed; no other combinations',
        'folds': 'first40/60/80 percent of frozen TRAIN dates; following20 percent internal validation',
        'embargo_seconds': 86400, 'purge': 'label_available_at strictly before boundary minus embargo',
        'validation_end': 'label_available_at strictly before fold end',
        'metrics': ['MSE_log_percent', 'MAE_log_percent', 'paired_MSE_difference_from_FULL'],
        'selection': False, 'active_model_changed': False, 'runtime_enabled': False,
        'input_hash': sha(fit / 'training_rows.json'), 'checkpoint_hash': sha(checkpoint),
        'code_hashes': {name: sha(ROOT / name) for name in (
            'scripts/audit_multifactor_ablation_dev.py', 'kquant_crypto/hybrid_factor_ablation.py',
            'kquant_crypto/hybrid_factor_experiments.py')}})
    result = train_ablation(json.loads((fit / 'training_rows.json').read_text()))
    write_json(out / 'report.json', result)
    print(json.dumps([{'train': f['train_rows'], 'validation': f['validation_rows'],
        'scores': [{k: v for k, v in s.items() if k != 'frozen_train_preprocessing'} for s in f['scores']]}
        for f in result['folds']]))


if __name__ == '__main__':
    main()
