import copy
import json

import pytest

from kquant_crypto.hybrid_clock import ClockSegment, POLICY, digest
from kquant_crypto.hybrid_hourly_receipt import normalize_hourly
from kquant_crypto.hybrid_factor_journal import FactorJournal

START = 1754006400000
CLOSE = START/1000+3600


def fixture():
    segment = ClockSegment(CLOSE-100+.1, CLOSE-100+.2, 100, CLOSE, 'probes', digest(POLICY))
    msg = dict(e='kline', E=int((CLOSE+.5)*1000), s='BTCUSDT', k=dict(
        t=START, T=START+3600000-1, s='BTCUSDT', i='1h', x=True,
        o='100', h='102', l='99', c='101', v='20'))
    return msg, segment


def test_preserves_source_and_rounds_receipt_up():
    msg, clock = fixture()
    before = copy.deepcopy(msg)
    result = normalize_hourly(msg, clock, monotonic_at=101, local_at=CLOSE+1)
    assert result['accepted']
    assert result['source_event_time_native_ms'] == msg['E']
    assert result['event']['payload']['received_at'] == CLOSE+2
    assert result['quote_evidence'] is False
    assert msg == before


@pytest.mark.parametrize('change', ['forming','missing_time','microseconds','boundary','symbol','nan','future'])
def test_rejects_bad_contract(change):
    msg, clock = fixture()
    if change == 'forming': msg['k']['x'] = False
    if change == 'missing_time': del msg['E']
    if change == 'microseconds': msg['E'] *= 1000
    if change == 'boundary': msg['k']['T'] += 1
    if change == 'symbol': msg['k']['s'] = 'ETHUSDT'
    if change == 'nan': msg['k']['c'] = 'nan'
    if change == 'future': msg['E'] += 10000
    result = normalize_hourly(msg, clock, monotonic_at=101, local_at=CLOSE+1)
    assert not result['accepted']
    assert 'event' not in result


def test_320_second_lag_not_relaxed():
    msg, clock = fixture()
    result = normalize_hourly(msg, clock, monotonic_at=420, local_at=CLOSE+320)
    assert result['reason'] == 'stale_quote'
    assert not result['accepted']


def test_expired_clock_and_local_step_rejected():
    msg, clock = fixture()
    for mono, local in ((701, CLOSE+601), (101, CLOSE+321)):
        assert not normalize_hourly(msg, clock, monotonic_at=mono, local_at=local)['accepted']


def test_receipt_provenance_survives_journal_recovery(tmp_path):
    msg, clock = fixture()
    path = tmp_path/'factor.sqlite3'
    contract = dict(first_close=int(CLOSE), receipt_basis='OBSERVED_RECEIPT', source='binance_spot_kline_1h')
    journal = FactorJournal(path, **contract)
    for symbol in ('BTCUSDT', 'ETHUSDT', 'SOLUSDT'):
        msg['s'] = msg['k']['s'] = symbol
        result = normalize_hourly(msg, clock, monotonic_at=101, local_at=CLOSE+1)
        event = result['event']
        journal.append(event['event_id'], event['payload'])
    rows = journal.advance('freeze', int(CLOSE+2))
    assert len(rows) == 3
    assert all(row['available_at'] == CLOSE+2 for row in rows)
    journal.close()
    journal = FactorJournal(path, **contract)
    _, count = journal.replay()
    assert count == 4
    payload = json.loads(journal.db.execute('SELECT payload FROM factor_events WHERE seq=1').fetchone()[0])
    assert payload['provenance']['source_event_time_native_ms'] == msg['E']
    assert payload['provenance']['quote_evidence'] is False
    journal.close()
