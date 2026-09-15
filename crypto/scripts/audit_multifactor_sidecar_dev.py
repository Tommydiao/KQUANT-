"""Review actual A27 plans against the completed DEV artifact, no formal writes."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dev_fit import CONFIG, DATA, audit, sha, write_json
from kquant_crypto.hybrid_multifactor_artifact import inspect_artifact
from kquant_crypto.hybrid_multifactor_sidecar import review_plan_evidence


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifact', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    model, out = [(ROOT / v).resolve() for v in (args.artifact, args.output)]
    if any(not p.is_relative_to(ROOT / 'outputs/hybrid_delivery') for p in (model, out)):
        raise ValueError('Independent research paths required')
    meta = inspect_artifact(model, purpose='DEV_ONLY')
    if meta['version'] != 'multifactor_entry_student_t_dev_v1':
        raise ValueError('Only frozen A27 entry artifact belongs to this audit')
    selected, source_audit = audit(json.loads(CONFIG.read_text()))
    opportunities = [json.loads(line) for line in (DATA / 'opportunities.jsonl').read_text().splitlines()]
    plans = {r['economic_signal_id']: r['plan'] for r in opportunities}
    if len(plans) != len(opportunities):
        raise ValueError('Duplicate source opportunities')
    training = json.loads((model / 'training_rows.json').read_text())
    targets = ROOT / 'outputs/hybrid_delivery/multifactor_entry_targets_20260907_01/entry_targets.jsonl'
    if sha(targets) != meta['target_hash']:
        raise ValueError('Frozen model training source changed')
    expected = [json.loads(line) for line in targets.read_text().splitlines()]
    expected = [r for r in expected if r['fill_status'] == 'VIRTUAL_FILLED' and r['label_status'] == 'MATURE']
    if training != expected or len(training) != len(selected):
        raise ValueError('Saved training membership mismatch')
    out.mkdir(exist_ok=False)
    write_json(out / 'contract.json', {'scope': 'DEV_ONLY', 'input_model_hash': meta['posterior_sha256'],
        'model_available_at': None, 'availability_note': 'No verified model registration clock; filesystem mtime not substituted',
        'training_rows_hash': sha(model / 'training_rows.json'), 'source_audit': source_audit,
        'writes': 'this output directory only; no original EVAL/PAPER/SHADOW registry',
        'source_code_hash': sha(ROOT / 'kquant_crypto/hybrid_multifactor_sidecar.py')})
    # Source labels are audited mature A27 observations, not unfilled opportunities.
    cutoff = max(r['label']['available_at'] for r in selected)
    reasons = Counter()
    with (out / 'reviews.jsonl').open('x', encoding='utf-8') as handle:
        for r in selected:
            label, feature = r['label'], r['feature']
            trade = label['executed_trade']
            original = plans[label['economic_signal_id']]
            plan = {'signal_id': label['economic_signal_id'], 'signal_time': label['signal_time'],
                'feature_available_at': feature['available_at'], 'symbol': label['symbol'],
                'mode': label['mode'], 'entry': original['entry_reference'], 'stop': original['stop'],
                'target': original['target'], 'execution_quality': 'LEGACY_BAR_PROXY',
                'strategy_gate': 'NO_GO', 'requested_target': 'LEGACY_BAR_PROXY_BASE_10_5_NET_R'}
            review = review_plan_evidence(meta, plan, purpose='DEV_ONLY',
                model_available_at=None, training_label_cutoff=cutoff)
            handle.write(json.dumps(review, sort_keys=True, allow_nan=False) + '\n')
            reasons.update(review['reasons'])
    result = {'scope': 'DEV_ONLY', 'reviewed_plans': len(selected), 'training_rows': len(training),
        'abstained': len(selected), 'reasons': dict(reasons), 'review_hash': sha(out / 'reviews.jsonl'),
        'formal_evaluations_written': 0, 'model_loaded_for_prediction': False,
        'historical_execution_claim': False, 'performance': 'PERFORMANCE_UNPROVEN'}
    write_json(out / 'report.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
