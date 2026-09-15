"""Run a synthetic durable recovery scenario and save independent evidence."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_delivery import atomic_json, sha
from kquant_crypto.hybrid_offline_stream_journal import OfflineStreamJournal
from kquant_crypto.hybrid_spot_stream_contract_v12 import MockConnection, OrderExpectation


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', required=True)
    a = p.parse_args()
    out = (ROOT / a.output).resolve()
    if not out.is_relative_to(ROOT / 'outputs/hybrid_delivery'):
        raise ValueError('Independent evidence output required')
    out.mkdir(parents=True, exist_ok=False)
    now = 1788580000000
    event = dict(e='executionReport', E=now+1, T=now, O=now-1000,
                 s='BTCUSDT', S='BUY', i=101, I=1, c='entry-1', C='',
                 x='CANCELED', X='CANCELED', o='LIMIT', f='IOC', q='1',
                 z='0.4', Z='40', l='0', L='0', Y='0', t=-1, r='NONE', n='0', N=None)
    envelope = {'subscriptionId': 0, 'event': event}
    connection = MockConnection('synthetic://recovery', 'fixed-fixture-v1', 0)
    expected = OrderExpectation('BTCUSDT', 101, 'entry-1', 'BUY', '1')
    journal = OfflineStreamJournal(out / 'journal', connection)
    try:
        journal.append(envelope, received_at_ms=now+10, expected=expected)
        atomic_json(out / 'before.json', journal.reconcile())
    finally:
        journal.close()
    trade = dict(event, I=2, x='TRADE', X='PARTIALLY_FILLED', l='0.4', L='100',
                 Y='40', t=20, n='0.04', N='USDT')
    journal = OfflineStreamJournal(out / 'journal', connection)
    try:
        fill = journal.append({'subscriptionId': 0, 'event': trade}, received_at_ms=now+11, expected=expected)
        duplicate = journal.append({'subscriptionId': 0, 'event': trade}, received_at_ms=now+12, expected=expected)
        after = journal.reconcile()
        atomic_json(out / 'after.json', after)
        assert fill.fill is not None and duplicate.duplicate_report
        assert 'CUMULATIVE_FILL_QUANTITY_MISMATCH' not in after['orders'][0]['reasons']
        assert after['status'] == 'REQUIRES_RECONCILIATION'
    finally:
        journal.close()
    atomic_json(out / 'evidence.json', {'scope': 'SYNTHETIC_RECOVERY_ONLY',
        'command': [sys.executable, *sys.argv], 'duplicate_suppressed': True,
        'unknown_fee_conversion_retained': True, 'G8': False, 'execution_allowed': False,
        'hashes': {p.name: sha(p) for p in (out / 'before.json', out / 'after.json',
                      out / 'journal/offline_stream_journal.sqlite3')}})
    print(json.dumps({'output': str(out), 'status': 'SYNTHETIC_SCENARIO_PASS'}))


if __name__ == '__main__':
    main()
