"""Export isolated reviews of existing forecasts; no refit or formal EVAL writes."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha, write_json
from kquant_crypto.hybrid_multifactor_artifact import inspect_artifact
from kquant_crypto.hybrid_population_sidecar import review_population


def main():
    p = argparse.ArgumentParser()
    for name in ('artifact', 'predictions', 'population', 'output'):
        p.add_argument('--'+name, required=True)
    args = p.parse_args()
    model, forecast, population, out = [(ROOT/getattr(args, k)).resolve()
        for k in ('artifact', 'predictions', 'population', 'output')]
    parent = ROOT/'outputs/hybrid_delivery'
    if any(not path.is_relative_to(parent) for path in (model, forecast, population, out)):
        raise ValueError('Independent research paths required')
    meta = inspect_artifact(model, purpose='DEV_ONLY')
    report = json.loads((forecast/'report.json').read_text())
    contract = json.loads((forecast/'diagnostic_contract.json').read_text())
    prediction_hash = sha(forecast/'predictions.jsonl')
    if (prediction_hash != report['prediction_hash']
        or contract['posterior_hash'] != meta['posterior_sha256']
        or sha(population/'population.jsonl') != meta['population_hash']):
        raise ValueError('Forecast/model/population hash mismatch')
    rows = [json.loads(s) for s in (population/'population.jsonl').read_text().splitlines()]
    train = [r for r in rows if r['partition'] == 'TRAIN' and r['exclusion_reason'] is None]
    if train != json.loads((model/'training_rows.json').read_text()):
        raise ValueError('Training provenance mismatch')
    predictions = [json.loads(s) for s in (forecast/'predictions.jsonl').read_text().splitlines()]
    reviews = review_population(meta, predictions, rows, prediction_hash=prediction_hash,
        training_label_cutoff=max(r['label_available_at'] for r in train))
    out.mkdir(exist_ok=False)
    with (out/'reviews.jsonl').open('x', encoding='utf-8') as f:
        for review in reviews:
            f.write(json.dumps(review, sort_keys=True, allow_nan=False)+'\n')
    reasons = Counter(reason for r in reviews for reason in r['research_review']['reasons'])
    result = dict(scope='DEV_ONLY_RETROSPECTIVE_FORECAST_COMPATIBILITY', rows=len(reviews),
        abstentions=sum(r['research_review']['decision'] == 'ABSTAIN' for r in reviews),
        reasons=dict(reasons), review_hash=sha(out/'reviews.jsonl'),
        prediction_hash=prediction_hash, posterior_hash=meta['posterior_sha256'],
        population_hash=meta['population_hash'], formal_eval_writes=0,
        execution_enabled=False, forward_acceptance=False, performance='PERFORMANCE_UNPROVEN',
        code_hashes={str(path.relative_to(ROOT)):sha(path) for path in (Path(__file__),
            ROOT/'kquant_crypto/hybrid_population_sidecar.py', ROOT/'kquant_crypto/hybrid_multifactor_sidecar.py',
            ROOT/'kquant_crypto/hybrid_target_contract.py')})
    write_json(out/'report.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
