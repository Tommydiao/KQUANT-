"""Score immutable saved forecasts without posterior sampling or fitting."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha, write_json
from kquant_crypto.hybrid_prediction_diagnostics import diagnostic_breakdown


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--population', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    base = ROOT / 'outputs/hybrid_delivery'
    population = (ROOT / args.population).resolve()
    out = (ROOT / args.output).resolve()
    forecast = base / 'multifactor_population_prediction_20260908_01'
    model = base / 'multifactor_population_fit_20260908_01'
    if not all(p.is_relative_to(base) for p in (population, out)) or out.exists():
        raise ValueError('Independent new output and research population required')
    meta = json.loads((model / 'artifact.json').read_text())
    report = json.loads((forecast / 'report.json').read_text())
    if sha(population / 'population.jsonl') != meta['population_hash'] or sha(forecast / 'predictions.jsonl') != report['prediction_hash']:
        raise ValueError('Frozen input hash mismatch')
    rows = [json.loads(s) for s in (population / 'population.jsonl').read_text().splitlines()]
    train = [r for r in rows if r['partition'] == 'TRAIN' and r['exclusion_reason'] is None]
    evaluate = [r for r in rows if r['partition'] == 'DEVELOPMENT_DIAGNOSTIC' and r['exclusion_reason'] is None]
    predictions = [json.loads(s) for s in (forecast / 'predictions.jsonl').read_text().splitlines()]
    if train != json.loads((model / 'training_rows.json').read_text()) or len(predictions) != len(evaluate):
        raise ValueError('Training or forecast population mismatch')
    for r, p in zip(evaluate, predictions):
        if (r['symbol'], r['as_of'], r['mode'], r['y_log_percent']) != (p['symbol'], p['as_of'], p['mode'], p['actual_log_percent']):
            raise ValueError('Forecast identity or label mismatch')
    result = diagnostic_breakdown(evaluate,
        [p['expected_log_percent'] for p in predictions],
        [p['positive_gross_probability_uncalibrated'] for p in predictions],
        [p['log_percent_quantiles05_50_95'][0] for p in predictions],
        [p['log_percent_quantiles05_50_95'][2] for p in predictions],
        training_mean=sum(r['y_log_percent'] for r in train) / len(train),
        training_positive_fraction=sum(r['y_log_percent'] > 0 for r in train) / len(train))
    result.update(prediction_hash=report['prediction_hash'], population_hash=meta['population_hash'],
                  refit=False, new_forecasts=False, code_hash=sha(Path(__file__)),
                  diagnostic_code_hash=sha(ROOT / 'kquant_crypto/hybrid_prediction_diagnostics.py'))
    out.mkdir(exist_ok=False)
    write_json(out / 'report.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
