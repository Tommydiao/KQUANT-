import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from kquant_crypto.hybrid_clock import ClockSegment, POLICY, digest


def module():
    spec = importlib.util.spec_from_file_location('rx07_v2', Path(__file__).resolve().parents[1]/'scripts/observe_rx07_dual_v2_dev.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_rejected_closed_bar_does_not_stop_raw_collection(tmp_path, monkeypatch):
    m = module()
    clock = [0.0]
    base = 1754010000
    segment = ClockSegment(base+.1, base+.2, 0, base, 'p', digest(POLICY))
    monkeypatch.setattr(m, 'time', SimpleNamespace(perf_counter=lambda: clock[0], time=lambda: base+clock[0]))
    async def probes(client, record):
        return []
    monkeypatch.setattr(m, 'probes', probes)
    monkeypatch.setattr(m, 'calibrate', lambda _: segment)
    class Socket:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def recv(self):
            clock[0] += 10
            closed = clock[0] == 10
            return json.dumps(dict(e='kline', E=int((base+20)*1000), s='BTCUSDT', k=dict(
                s='BTCUSDT', i='5m', x=closed, t=(base-300)*1000, T=base*1000-1,
                o='100',h='102',l='99',c='101',v='1')))
    monkeypatch.setattr(m, 'connect', lambda *args, **kwargs: Socket())
    result = asyncio.run(m.observe(tmp_path/'run', 25))
    assert result['failure'] is None
    assert result['counts']['messages'] == 3
    assert result['counts']['reason:quote_receipt_order_uncertain'] == 1
    assert result['counts']['reason:forming_bar'] == 2
    assert result['eligibility_failures'] == 1
    assert result['receive_seconds'] == 30
    assert not result['strict_data_pass'] and not result['signal_ready']
    assert not result['execution_ready'] and result['quote_labels'] == 0
    assert result['status'] == 'RAW_RECEIPT_SEGMENT_COMPLETE'


def test_missing_history_not_repaired_by_later_bar():
    m = module()
    ledger = m.ClosedLedger(3500)
    row = dict(symbol='BTCUSDT', interval='5m', event_id='late', close_time=3900, bar=dict(close=100))
    try:
        ledger.accept(row)
    except ValueError as exc:
        assert str(exc) == 'closed_bar_gap_or_out_of_order'
    else:
        raise AssertionError('gap must remain rejected')
    assert not ledger.seen
    assert ledger.expected[('BTCUSDT', '5m')] == 3600
