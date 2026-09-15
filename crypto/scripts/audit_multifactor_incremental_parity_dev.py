"""Real historical values through incremental ingestion; receipt clock is synthetic."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dataset import load_development
from kquant_crypto.hybrid_dev_fit import sha, write_json
from kquant_crypto.hybrid_incremental_factors import IncrementalFactors
from kquant_crypto.hybrid_multifactor_dev import CORE_SYMBOLS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    out = (ROOT / parser.parse_args().output).resolve()
    parent = ROOT / 'outputs/hybrid_delivery'
    if not out.is_relative_to(parent):
        raise ValueError('Independent research output required')
    source = parent / 'multifactor_dataset_20260907_06'
    meta = json.loads((source / 'report.json').read_text())
    if sha(source / 'features.jsonl') != meta['features_hash']:
        raise ValueError('Frozen feature source mismatch')
    expected = {}
    for line in (source / 'features.jsonl').read_text().splitlines():
        row = json.loads(line)
        expected[row['symbol'], row['as_of']] = {r['factor_id']: r['value'] for r in row['factor_contract']['factors']}
    data = load_development(ROOT / 'outputs/dual_regime_v1/frozen/data_manifest.json')
    if data.content_hash != meta['dataset_hash']:
        raise ValueError('Different authorized history')
    first = {data.bars[s]['1h'][0].start + 3600 for s in CORE_SYMBOLS}
    if len(first) != 1:
        raise ValueError('Warmup calendars differ')
    engine = IncrementalFactors(first.pop(), receipt_basis='REPLAY_CLOCK_FIXTURE', source=data.manifest['source'])
    by_close = {}
    for s in CORE_SYMBOLS:
        for b in data.bars[s]['1h']:
            by_close.setdefault(b.start + 3600, {})[s] = b
    out.mkdir(exist_ok=False)
    write_json(out / 'contract.json', {'scope': 'DEV_ONLY', 'receipt_basis': 'REPLAY_CLOCK_FIXTURE',
        'receipt_delay_seconds': 1, 'not_measured_live_latency': True,
        'comparison': 'all19factor values; availability and hash intentionally differ from historical proxy',
        'dataset_hash': data.content_hash, 'expected_features_hash': meta['features_hash'],
        'execution_enabled': False, 'code_hash': sha(ROOT / 'kquant_crypto/hybrid_incremental_factors.py')})
    checked, values = 0, 0
    for stamp, bars in sorted(by_close.items()):
        for s in reversed(CORE_SYMBOLS):
            if s in bars:
                engine.ingest(s, bars[s], received_at=stamp + 1, closed=True)
        if engine.advance(stamp):
            raise ValueError('Consumed before receipt')
        for row in engine.advance(stamp + 1):
            key = row['symbol'], row['as_of']
            if key not in expected:
                continue
            got = {r['factor_id']: r['value'] for r in row['factor_contract']['factors']}
            if got != expected[key]:
                raise ValueError('Incremental/batch factor mismatch: ' + str(key))
            if any(r['available_at'] != stamp + 1 for r in row['factor_contract']['factors']):
                raise ValueError('Receipt provenance lost')
            checked += 1
            values += len(got)
    if checked != len(expected):
        raise ValueError('Not every frozen hourly snapshot compared')
    result = {'scope': 'DEV_ONLY', 'snapshots_compared': checked, 'factor_values_compared': values,
        'value_parity': 'PASS', 'receipt_clock': 'SYNTHETIC_FIXTURE_NOT_LIVE',
        'real_time_acceptance': False, 'provider_started': False,
        'execution_enabled': False, 'performance': 'PERFORMANCE_UNPROVEN'}
    write_json(out / 'report.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
