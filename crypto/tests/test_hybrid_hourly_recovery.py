import copy
from dataclasses import asdict
import json
import math
import hashlib
import importlib.util
from pathlib import Path

import pytest
from kquant_crypto.hybrid_clock import calibrate, digest
from kquant_crypto.hybrid_hourly_receipt import normalize_hourly
from kquant_crypto.hybrid_hourly_recovery import validate_log, replay_actions
from kquant_crypto.hybrid_factor_journal import FactorJournal

START = 1754006400000
CLOSE = START//1000+3600


def log_fixture():
    probes = [dict(monotonic_before=90+2*i, monotonic_after=90.2+2*i,
        local_before=CLOSE-10+2*i, local_after=CLOSE-9.8+2*i,
        serverTime=int((CLOSE-9.9+2*i)*1000)) for i in range(5)]
    clock = calibrate(probes)
    rows = [dict(state='RECEIVED', sample=p) for p in probes]
    rows.append(dict(kind='clock_segment', segment=asdict(clock), segment_id=clock.segment_id))
    rows.append(dict(kind='journal_contract', first_close=CLOSE, receipt_basis='OBSERVED_RECEIPT',
        source='binance_spot_native_utc_kline_1h'))
    for seq, symbol in enumerate(('BTCUSDT', 'ETHUSDT', 'SOLUSDT'), 1):
        mono = 101+seq
        msg = dict(e='kline', E=(CLOSE*1000+500), s=symbol, k=dict(t=START,
            T=START+3600000-1, s=symbol, i='1h', x=True, o='100', h='102', l='99', c='101', v='20'))
        rows.append(dict(kind='raw_message', sequence=seq, raw=json.dumps(msg),
            received_at_monotonic=mono, received_at_local_utc=CLOSE+mono-100,
            clock_segment_id=clock.segment_id))
        result = normalize_hourly(msg, clock, monotonic_at=mono, local_at=CLOSE+mono-100)
        rows.append(dict(kind='normalization', sequence=seq, result=result))
        receipt = clock.bounds(mono+.1, CLOSE+mono-99.9)
        rows.append(dict(kind='freeze_intent', sequence=seq, event_id=result['event']['event_id'],
            event_hash=digest(result['event']), receipt=receipt,
            frozen_at=math.ceil(receipt['received_at_upper'])))
    return rows


def test_crash_after_intent_recovers_once_with_recorded_availability(tmp_path):
    rows = log_fixture()
    before = copy.deepcopy(rows)
    contract, actions, counts = validate_log(rows)
    journal = FactorJournal(tmp_path/'f.sqlite3', **contract)
    assert replay_actions(journal, actions) == 3
    _, count = journal.replay()
    assert count == 6
    assert replay_actions(journal, actions) == 3
    assert journal.replay()[1] == 6
    journal.close()
    assert rows == before
    assert counts['freezes'] == 3


def test_missing_last_intent_does_not_invent_freeze(tmp_path):
    contract, actions, counts = validate_log(log_fixture()[:-1])
    journal = FactorJournal(tmp_path/'f.sqlite3', **contract)
    assert replay_actions(journal, actions) == 0
    assert counts['accepted_without_freeze'] == 1
    assert journal.replay()[1] == 5
    journal.close()


@pytest.mark.parametrize('change', ['time', 'event_hash', 'sequence', 'normalization', 'clock'])
def test_corrupt_receipts_rejected(change):
    rows = log_fixture()
    if change == 'time': rows[-1]['frozen_at'] += 1
    if change == 'event_hash': rows[-1]['event_hash'] = 'changed'
    if change == 'sequence': rows[-3]['sequence'] += 1
    if change == 'normalization': rows[-2]['result']['accepted'] = False
    if change == 'clock': rows[5]['segment']['offset_upper'] += .1
    with pytest.raises(ValueError):
        validate_log(rows)


def test_independent_command_creates_replay_and_preserves_source(tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('recover_hourly', root/'scripts/recover_multifactor_hourly_dev.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path/'source'
    source.mkdir()
    hashes = {str(Path('kquant_crypto')/name): hashlib.sha256((root/'kquant_crypto'/name).read_bytes()).hexdigest()
        for name in ('hybrid_hourly_receipt.py', 'hybrid_clock.py', 'hybrid_factor_journal.py')}
    (source/'manifest.json').write_text(json.dumps(dict(scope='DEV_ONLY', execution_enabled=False, source_hashes=hashes)))
    (source/'receipts.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in log_fixture()))
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    out = tmp_path/'recovery'
    result = module.recover(source, out)
    assert result['status'] == 'RECOVERED' and result['recovered_snapshots'] == 3
    assert result['execution_enabled'] is False
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before
    with pytest.raises(ValueError, match='must be new'):
        module.recover(source, out)
    path = source/'receipts.jsonl'
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(ValueError, match='truncated'):
        module.recover(source, tmp_path/'truncated')
    assert not (tmp_path/'truncated').exists()
