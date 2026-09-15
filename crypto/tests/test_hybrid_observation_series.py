import importlib.util
import json
from pathlib import Path
import pytest


@pytest.fixture
def series(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'scripts/run_hybrid_observation_series.py'
    spec = importlib.util.spec_from_file_location('series_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'scripts/run_hybrid_continuous_observer.py').write_text('fixture only')
    clock = [100.0]
    monkeypatch.setattr(module.time, 'perf_counter', lambda: clock[0])
    monkeypatch.setattr(module.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    return module


def test_only_terminal_connection_failure_retries(series):
    report = {'state': 'FAILED', 'execution_enabled': False, 'failure': {'type': 'ConnectionClosedError'}}
    assert series.retry_allowed(1, report)
    assert not series.retry_allowed(0, report)
    assert not series.retry_allowed(1, {})
    assert not series.retry_allowed(1, report | {'execution_enabled': True})
    assert not series.retry_allowed(1, report | {'failure': {'type': 'ValueError'}})
    assert series.retry_allowed(1, report | {'failure': {'type': 'ConnectError'}})
    assert not series.retry_allowed(1, report | {'failure': {'type': 'HTTPStatusError'}})


def test_public_child_does_not_inherit_private_credentials(series, monkeypatch):
    monkeypatch.setenv('BINANCE_LIVE_API_SECRET', 'not-a-real-secret')
    monkeypatch.setenv('OPENAI_API_KEY', 'not-a-real-key')
    monkeypatch.setenv('HTTPS_PROXY', 'https://not-used')
    env = series.child_environment()
    assert not any(k in env for k in ('BINANCE_LIVE_API_SECRET', 'OPENAI_API_KEY', 'HTTPS_PROXY'))


@pytest.mark.parametrize('failure_type', ['ConnectionClosedError', 'ConnectError'])
def test_terminal_failure_new_segments_and_budget(series, tmp_path, monkeypatch, failure_type):
    created = []
    class Child:
        def __init__(self, command, **kwargs):
            folder = Path(command[command.index('--output') + 1])
            folder.mkdir()
            assert not created or created[-1].returncode is not None
            self.pid = 1000 + len(created)
            self.returncode = 1
            created.append(self)
            (folder / 'report.json').write_text(json.dumps({'state': 'FAILED', 'execution_enabled': False,
                'failure': {'type': failure_type}}))
        def poll(self):
            return self.returncode
    monkeypatch.setattr(series.subprocess, 'Popen', Child)
    out = tmp_path / 'outputs/hybrid_regime_v1/series'
    assert series.execute(out, 600, 2) == 1
    report = json.loads((out / 'report.json').read_text())
    assert len(created) == 2
    assert report['state'] == 'SEGMENT_BUDGET_EXHAUSTED'
    assert not report['G3_passed'] and not report['uninterrupted_72h_passed']
    assert len({a['segment'] for a in report['attempts']}) == 2
    with pytest.raises(FileExistsError):
        series.execute(out, 600, 2)


def test_unknown_child_exit_does_not_restart(series, tmp_path, monkeypatch):
    class Child:
        pid, returncode = 1, 1
        def __init__(self, *args, **kwargs): pass
        def poll(self): return self.returncode
    monkeypatch.setattr(series.subprocess, 'Popen', Child)
    out = tmp_path / 'outputs/hybrid_regime_v1/unknown'
    assert series.execute(out, 600, 12) == 1
    report = json.loads((out / 'report.json').read_text())
    assert len(report['attempts']) == 1
    assert report['state'] == 'BLOCKED_NONRETRYABLE_FAILURE'


def test_stop_timeout_only_terminates_owned_handle_without_new_segment(series, tmp_path, monkeypatch):
    children = []
    class Child:
        pid, returncode = 11, None
        def __init__(self, *args, **kwargs): children.append(self)
        def poll(self): return self.returncode
        def terminate(self): self.returncode = -1
        def wait(self, timeout): assert timeout == 15; return self.returncode
    monkeypatch.setattr(series.subprocess, 'Popen', Child)
    out = tmp_path / 'outputs/hybrid_regime_v1/stopping'
    assert series.execute(out, 30, 12) == 1
    report = json.loads((out / 'report.json').read_text())
    assert len(children) == 1 and children[0].returncode == -1
    assert report['state'] == 'BLOCKED_CHILD_STOP_TIMEOUT'
    assert not (out / 'segment_001').exists()
    assert report['attempts'][0]['forced_owned_child_termination']


def test_budget_end_does_not_hide_clock_failure(series, tmp_path, monkeypatch):
    class Child:
        pid, returncode = 1, 1
        def __init__(self, command, **kwargs):
            folder = Path(command[command.index('--output') + 1])
            folder.mkdir()
            (folder / 'report.json').write_text(json.dumps({'state': 'FAILED', 'execution_enabled': False,
                'failure': {'type': 'ValueError', 'contract_detail': 'Invalid clock probe duration'}}))
            series.time.sleep(31)
        def poll(self): return self.returncode
    monkeypatch.setattr(series.subprocess, 'Popen', Child)
    out = tmp_path / 'outputs/hybrid_regime_v1/clock_fail'
    assert series.execute(out, 30, 12) == 1
    report = json.loads((out / 'report.json').read_text())
    assert report['state'] == 'BUDGET_OR_STOP_WITH_CHILD_FAILURE'
    assert len(report['attempts']) == 1


def test_transient_windows_status_lock_has_finite_retries(series, tmp_path, monkeypatch):
    original = series.atomic_json
    calls = []
    def locked(path, body):
        calls.append(path)
        if len(calls) < 3: raise PermissionError('fixture sharing violation')
        original(path, body)
    monkeypatch.setattr(series, 'atomic_json', locked)
    series.write_status(tmp_path / 'status.json', {'state': 'RUNNING'})
    assert len(calls) == 3


def test_persistent_status_io_stops_only_owned_child_and_saves_failure(series, tmp_path, monkeypatch):
    original = series.atomic_json
    def locked(path, body):
        if Path(path).name == 'status.json': raise PermissionError('fixture sharing violation')
        original(path, body)
    monkeypatch.setattr(series, 'atomic_json', locked)
    children = []
    class Child:
        pid, returncode = 11, None
        def __init__(self, command, **kwargs):
            Path(command[command.index('--output') + 1]).mkdir()
            children.append(self)
        def poll(self): return self.returncode
        def wait(self, timeout):
            assert timeout == 45
            self.returncode = 0
            return 0
    monkeypatch.setattr(series.subprocess, 'Popen', Child)
    out = tmp_path / 'outputs/hybrid_regime_v1/io_fail'
    assert series.execute(out, 600, 12) == 1
    report = json.loads((out / 'manager_failure.json').read_text())
    assert report['state'] == 'BLOCKED_STATUS_IO'
    assert len(children) == 1 and children[0].returncode == 0
    assert (out / 'segment_001/STOP').exists()
    assert not report['G3_passed']
