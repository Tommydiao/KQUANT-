"""Fixed calendar influence audit of previously frozen training rows only."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha, write_json
from kquant_crypto.hybrid_factor_block_sensitivity import sensitivity


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    parent = ROOT/'outputs/hybrid_delivery'
    out = (ROOT/args.output).resolve()
    if not out.is_relative_to(parent):
        raise ValueError('Independent research output required')
    checkpoint = parent/'multifactor_pause_20260907_01/checkpoint.json'
    audit = json.loads(checkpoint.read_text())
    source = (ROOT/audit['fit_path']/'training_rows.json').resolve()
    if not source.is_relative_to(parent) or sha(source) != audit['fit_files']['training_rows.json']:
        raise ValueError('Frozen training input mismatch')
    out.mkdir(exist_ok=False)
    write_json(out/'preregistration.json', dict(scope='DEV_ONLY_EXPOSED_RESEARCH',
        calendar_block_days=7, anchor='first frozen TRAIN UTC date',
        tail='retain and explicitly mark partial block', metric='Spearman rank correlation',
        variants='remove each consecutive calendar block across all three coins together',
        selection=False, refit=False, activation=False, input_hash=sha(source),
        checkpoint_hash=sha(checkpoint), code_hash=sha(Path(__file__)),
        kernel_hash=sha(ROOT/'kquant_crypto/hybrid_factor_block_sensitivity.py')))
    result = sensitivity(json.loads(source.read_text()))
    write_json(out/'report.json', result)
    print(json.dumps({k: v for k, v in result.items() if k != 'blocks'}))


if __name__ == '__main__':
    main()
