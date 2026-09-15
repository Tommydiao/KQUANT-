import asyncio
import importlib.util
import json
from pathlib import Path

import pytest


def module():
    path = Path(__file__).resolve().parents[1]/'scripts/observe_multifactor_hourly_dev.py'
    spec = importlib.util.spec_from_file_location('hour_observer', path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_clock_failure_archived_without_factor_store(tmp_path, monkeypatch):
    m = module()
    async def fail(client, record):
        record(dict(state='FAILED', error_type='ClockTestFailure'))
        raise ValueError('clock rejected')
    monkeypatch.setattr(m, 'probes', fail)
    out = tmp_path/'run'
    result = asyncio.run(m.observe(out, 1))
    assert result['status'] == 'FAILED'
    assert result['failure']['detail'] == 'clock rejected'
    assert result['execution_enabled'] is False
    assert not (out/'factors.sqlite3').exists()
    rows = [json.loads(s) for s in (out/'receipts.jsonl').read_text().splitlines()]
    assert rows[-1]['kind'] == 'terminal_failure'
    assert json.loads((out/'report.json').read_text()) == result


def test_existing_output_never_overwritten(tmp_path):
    m = module()
    with pytest.raises(FileExistsError):
        asyncio.run(m.observe(tmp_path, 1))


def test_freeze_intent_precedes_every_journal_write():
    m = module()
    calls = []
    class Journal:
        def append(self, event_id, payload):
            calls.append('ingest')
            return 'INSERTED'
        def advance(self, event_id, frozen):
            calls.append(('advance', event_id, frozen))
            return []
    records = []
    def record(row):
        calls.append(row['kind'])
        records.append(row)
    event = dict(event_id='bar:1', payload=dict(kind='ingest'))
    m.commit_receipt(Journal(), record, event, 7, dict(received_at_upper=3600.2))
    assert calls == ['freeze_intent', 'ingest', ('advance', 'freeze:7', 3601), 'journal_commit']
    assert records[0]['event_hash'] == m.digest(event)
    assert records[0]['frozen_at'] == records[1]['frozen_at'] == 3601


def test_failed_intent_persistence_prevents_journal_writes():
    m = module()
    class Journal:
        def append(self, *args):
            pytest.fail('No write allowed before durable intent')
        def advance(self, *args):
            pytest.fail('No freeze allowed before durable intent')
    def fail(row):
        raise OSError('disk full')
    with pytest.raises(OSError, match='disk full'):
        m.commit_receipt(Journal(), fail, dict(event_id='bar:1', payload={}),
                         1, dict(received_at_upper=3600.2))


@pytest.mark.parametrize('failure', ['ingest', 'advance'])
def test_journal_failure_retains_original_freeze_evidence(failure):
    m = module()
    records = []
    class Journal:
        def append(self, *args):
            if failure == 'ingest':
                raise OSError('database failure')
            return 'INSERTED'
        def advance(self, *args):
            raise OSError('database failure')
    with pytest.raises(OSError, match='database failure'):
        m.commit_receipt(Journal(), records.append, dict(event_id='bar:1', payload={}),
                         1, dict(received_at_upper=3600.2))
    assert len(records) == 1
    assert records[0]['kind'] == 'freeze_intent'
    assert records[0]['frozen_at'] == 3601
