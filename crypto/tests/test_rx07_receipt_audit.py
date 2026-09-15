import importlib.util
import json
from pathlib import Path
from dataclasses import asdict

import pytest
from kquant_crypto.hybrid_clock import ClockSegment, POLICY, digest
from kquant_crypto.hybrid_dual_receipt import normalize_closed


def module():
    spec = importlib.util.spec_from_file_location('audit_rx07', Path(__file__).resolve().parents[1]/'scripts/audit_rx07_receipts_dev.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def records():
    clock = ClockSegment(1754009900.1,1754009900.2,100,1754010000,'p',digest(POLICY))
    msg = dict(e='kline', s='BTCUSDT', k=dict(s='BTCUSDT', i='5m', x=False))
    source = dict(kind='raw_message', sequence=1, raw=json.dumps(msg),
        received_at_monotonic=101, received_at_local_utc=1754010001, clock_segment_id=clock.segment_id)
    result = normalize_closed(msg, clock, monotonic_at=101, local_at=1754010001)
    return [dict(kind='clock_segment', segment=asdict(clock), segment_id=clock.segment_id),
            source, dict(kind='normalization', sequence=1, result=result)]


def encode(rows):
    return ''.join(json.dumps(r)+'\n' for r in rows).encode()


def test_replay_and_pending_prefix():
    m = module()
    result = m.verify(encode(records()))
    assert result['counts']['reason:forming_bar'] == 1
    assert not result['continuity_pass']
    assert m.verify(encode(records()[:-1]))['unresolved_raw_sequences'] == [1]


def test_serialized_clock_without_probes_is_not_strict_evidence():
    with pytest.raises(ValueError, match='preregistered number'):
        module().verify(encode(records()), require_probes=True)


@pytest.mark.parametrize('bad', ['result', 'sequence', 'clock', 'truncated'])
def test_corruption_detected(bad):
    rows = records()
    if bad == 'result': rows[-1]['result']['accepted'] = True
    if bad == 'sequence': rows[1]['sequence'] = 2
    if bad == 'clock': rows[0]['segment_id'] = 'bad'
    data = encode(rows)
    if bad == 'truncated': data = data[:-1]
    with pytest.raises(ValueError):
        module().verify(data)
