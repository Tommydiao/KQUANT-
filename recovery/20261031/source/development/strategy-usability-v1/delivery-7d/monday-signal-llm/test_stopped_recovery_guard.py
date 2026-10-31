import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('stopped_recovery_guard',HERE/'apply_stopped_candidate.py')
guard=importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def setup_root(tmp_path,monkeypatch,*,state='STOPPED',listeners=None):
    path=tmp_path/'runtime/work/option_foundation/runtime/services.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(dict(state=state,listeners=listeners or [],backend_release='TEST_ONLY_OLD')))
    monkeypatch.setattr(guard,'ROOT',tmp_path)
    return path


def test_running_manifest_rejects_before_os_action(tmp_path,monkeypatch):
    setup_root(tmp_path,monkeypatch,state='RUNNING')
    monkeypatch.setattr(guard.subprocess,'run',lambda *a,**k:pytest.fail('Unexpected process operation'))
    with pytest.raises(ValueError,match='ALREADY_STOPPED'):
        guard.require_stopped_root()


def test_recorded_listener_rejects_before_os_action(tmp_path,monkeypatch):
    setup_root(tmp_path,monkeypatch,listeners=[dict(port=8001)])
    monkeypatch.setattr(guard.subprocess,'run',lambda *a,**k:pytest.fail('Unexpected process operation'))
    with pytest.raises(ValueError,match='ALREADY_STOPPED'):
        guard.require_stopped_root()


def test_actual_os_busy_rejects_and_preserves_manifest(tmp_path,monkeypatch):
    path=setup_root(tmp_path,monkeypatch)
    before=path.read_bytes()
    def busy(*a,**k): raise subprocess.CalledProcessError(12,a[0])
    monkeypatch.setattr(guard.subprocess,'run',busy)
    with pytest.raises(subprocess.CalledProcessError): guard.require_stopped_root()
    assert path.read_bytes()==before


def test_verified_stopped_check_never_stops_or_writes(tmp_path,monkeypatch):
    path=setup_root(tmp_path,monkeypatch)
    before=path.read_bytes()
    commands=[]
    def checked(command,**kwargs):
        commands.append(command)
        assert 'Stop-Process' not in command[-1]
        assert 'Get-NetTCPConnection' in command[-1] and 'Get-CimInstance' in command[-1]
    monkeypatch.setattr(guard.subprocess,'run',checked)
    assert guard.require_stopped_root()['backend_release']=='TEST_ONLY_OLD'
    assert len(commands)==1 and path.read_bytes()==before
