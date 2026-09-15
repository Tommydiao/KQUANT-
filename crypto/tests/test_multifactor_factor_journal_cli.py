import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def cli(tmp_path):
    script = Path(__file__).resolve().parents[1]/'scripts/run_multifactor_factor_journal_dev.py'
    spec = importlib.util.spec_from_file_location('factor_cli', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path
    return module


def test_consume_recover_and_status(tmp_path):
    m = cli(tmp_path)
    contract = tmp_path/'contract.json'
    contract.write_text(json.dumps(dict(first_close=3600, receipt_basis='REPLAY_CLOCK_FIXTURE', source='fixture')))
    inputs = tmp_path/'input.jsonl'
    inputs.write_text(json.dumps(dict(event_id='clock', payload=dict(kind='advance', frozen_at=3601)))+'\n')
    args = SimpleNamespace(command='consume', run_id='test', input=str(inputs), contract=str(contract), limit=1000)
    assert m.run(args)['inserted'] == 1
    assert m.run(args)['idempotent'] == 1
    args.command = 'status'
    assert m.run(args)['count'] == 1


def test_status_missing_does_not_create_store(tmp_path):
    m = cli(tmp_path)
    assert m.run(SimpleNamespace(command='status', run_id='new'))['status'] == 'NOT_STARTED'
    assert not (tmp_path/'work').exists()


def test_path_escape_rejected(tmp_path):
    with pytest.raises(ValueError, match='run ID'):
        cli(tmp_path).run(SimpleNamespace(command='status', run_id='../old'))


def test_changed_file_cannot_resume_at_old_offset(tmp_path):
    m = cli(tmp_path)
    contract = tmp_path/'contract.json'
    contract.write_text(json.dumps(dict(first_close=3600, receipt_basis='REPLAY_CLOCK_FIXTURE', source='fixture')))
    inputs = tmp_path/'input.jsonl'
    event = dict(event_id='clock', payload=dict(kind='advance', frozen_at=3601))
    inputs.write_text(json.dumps(event)+'\n')
    args = SimpleNamespace(command='consume', run_id='bound', input=str(inputs), contract=str(contract), limit=1, offset=0)
    first = m.run(args)
    assert len(first['input_sha256']) == 64
    args.offset = 1
    assert m.run(args)['inserted'] == 0
    inputs.write_text(json.dumps(event)+'\n\n')
    with pytest.raises(ValueError, match='Frozen input mismatch'):
        m.run(args)
    args.command = 'status'
    assert m.run(args)['count'] == 1


def test_offset_outside_file_rejected_before_store_creation(tmp_path):
    m = cli(tmp_path)
    contract = tmp_path/'contract.json'
    contract.write_text(json.dumps(dict(first_close=3600, receipt_basis='REPLAY_CLOCK_FIXTURE', source='fixture')))
    inputs = tmp_path/'input.jsonl'
    inputs.write_text('')
    with pytest.raises(ValueError, match='Offset exceeds'):
        m.run(SimpleNamespace(command='consume', run_id='bad', input=str(inputs), contract=str(contract), limit=1, offset=1))
    assert not (tmp_path/'work').exists()
