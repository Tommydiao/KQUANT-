import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha, write_json
from kquant_crypto.hybrid_holding_overlap_audit import audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    source = ROOT / 'outputs/hybrid_delivery/multifactor_policy_holding_v2_20260908_01'
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to(ROOT / 'outputs/hybrid_delivery'):
        raise ValueError('Independent output required')
    report = json.loads((source / 'report.json').read_text())
    labels = source / 'holding_targets.jsonl'
    if sha(labels) != report['labels_hash']:
        raise ValueError('Frozen holding hash mismatch')
    rows = [json.loads(line) for line in labels.read_text().splitlines()]
    result = audit(rows, 1767225600)
    result.update(source_labels_hash=report['labels_hash'], observations=len(rows),
                  boundary_basis='Existing population TRAIN boundary, not newly selected')
    output.mkdir(exist_ok=False)
    write_json(output / 'report.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
