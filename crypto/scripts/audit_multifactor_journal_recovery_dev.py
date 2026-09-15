"""Actual authorized bar values, synthetic receipts, independent recovery audit."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dataset import load_development
from kquant_crypto.hybrid_dev_fit import sha, write_json
from kquant_crypto.hybrid_factor_journal import FactorJournal
from kquant_crypto.hybrid_incremental_factors import IncrementalFactors
from kquant_crypto.hybrid_multifactor_dev import CORE_SYMBOLS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    out = (ROOT / args.output).resolve()
    if not out.is_relative_to(ROOT / 'outputs/hybrid_delivery'):
        raise ValueError('Independent research path required')
    data = load_development(ROOT / 'outputs/dual_regime_v1/frozen/data_manifest.json')
    count = 251
    bars = {s: data.bars[s]['1h'][:count] for s in CORE_SYMBOLS}
    firsts = {b[0].start+3600 for b in bars.values()}
    if len(firsts) != 1 or any(len(b) != count for b in bars.values()):
        raise ValueError('Common warmup unavailable')
    contract = dict(first_close=firsts.pop(), receipt_basis='REPLAY_CLOCK_FIXTURE', source=data.manifest['source'])
    out.mkdir(exist_ok=False)
    write_json(out / 'contract.json', dict(contract, dataset_hash=data.content_hash,
        hours=count, receipt_delay_seconds=1, reopen_after_hours=125,
        scope='DEV_ONLY', real_time_acceptance=False, execution_enabled=False))
    baseline = IncrementalFactors(**contract)
    path = out / 'factor_recovery.sqlite3'
    journal = FactorJournal(path, **contract)
    started = time.monotonic()
    compared = ready = 0
    try:
        for i in range(count):
            stamp = bars[CORE_SYMBOLS[0]][i].start+3600
            for symbol in reversed(CORE_SYMBOLS):
                b = bars[symbol][i]
                baseline.ingest(symbol, b, received_at=stamp+1, closed=True)
                journal.ingest(f'{symbol}:{stamp}', symbol, b, received_at=stamp+1, closed=True)
            expected = baseline.advance(stamp+1)
            got = journal.advance(f'freeze:{stamp}', stamp+1)
            if got != expected:
                raise ValueError('Recovered snapshot mismatch')
            compared += len(got)
            ready += sum(all(f['status']=='AVAILABLE' for f in r['factor_contract']['factors']) for r in got)
            if i == 124:
                journal.close()
                journal = FactorJournal(path, **contract)
                if journal.advance(f'freeze:{stamp}', stamp+1) != got:
                    raise ValueError('Duplicate across restart differs')
        events = journal.db.execute('SELECT COUNT(*) FROM factor_events').fetchone()[0]
        result = dict(scope='DEV_ONLY', snapshots_compared=compared,
            all_factors_ready_snapshots=ready, saved_events=events,
            restart_duplicate_insertions=0, recovery='PASS',
            elapsed_seconds=time.monotonic()-started, execution_enabled=False,
            real_time_acceptance=False, receipt_clock='SYNTHETIC_FIXTURE_NOT_LIVE')
    finally:
        journal.close()
    result['database_hash'] = sha(path)
    write_json(out / 'report.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
