import asyncio
import importlib.util
import json
from pathlib import Path

import pytest


def module():
    spec = importlib.util.spec_from_file_location('rx07', Path(__file__).resolve().parents[1]/'scripts/observe_rx07_dual_dev.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def row(symbol='BTCUSDT', close=3600):
    return dict(symbol=symbol, interval='5m', close_time=close,
                event_id=f'{symbol}:{close}', bar=dict(close=100))


def test_closed_batches_duplicates_conflicts_and_gaps():
    ledger = module().ClosedLedger(3500)
    assert ledger.accept(row()) == 'new_closed_bar'
    assert ledger.accept(row()) == 'duplicate'
    assert ledger.accept(row('ETHUSDT')) == 'new_closed_bar'
    assert ledger.accept(row('SOLUSDT')) == 'synchronized_batch'
    bad = row()
    bad['bar']['close'] = 101
    with pytest.raises(ValueError, match='conflicting'):
        ledger.accept(bad)
    with pytest.raises(ValueError, match='gap_or_out_of_order'):
        ledger.accept(row(close=4200))
    assert ledger.expected[('BTCUSDT', '5m')] == 3900


def test_initial_calibration_failure_durable(tmp_path, monkeypatch):
    m = module()
    async def fail(client, record):
        record(dict(kind='probe_failed'))
        raise ValueError('clock failure')
    monkeypatch.setattr(m, 'probes', fail)
    out = tmp_path/'run'
    result = asyncio.run(m.observe(out, 1))
    assert result['status'] == 'FAILED'
    assert not result['signal_ready'] and not result['execution_ready']
    assert result['receive_seconds'] is None
    assert result['receive_window_completed'] is False
    rows = [json.loads(x) for x in (out/'receipts.jsonl').read_text().splitlines()]
    assert rows[-1]['kind'] == 'terminal_failure'
    with pytest.raises(FileExistsError):
        asyncio.run(m.observe(out, 1))


def test_invalid_duration_creates_nothing(tmp_path):
    with pytest.raises(ValueError):
        asyncio.run(module().observe(tmp_path/'run', 0))
    assert not (tmp_path/'run').exists()
