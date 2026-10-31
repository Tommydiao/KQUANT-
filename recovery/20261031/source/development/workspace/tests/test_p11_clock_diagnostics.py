from datetime import UTC, datetime
from threading import Event, RLock, Thread
from types import SimpleNamespace

from kquant.options_radar_supervisor import OptionRadarSupervisor
from kquant.research_runtime_health import RuntimeDiagnostics


def test_worker_status_exposes_only_already_collected_source_snapshots(tmp_path):
    supervisor = OptionRadarSupervisor(tmp_path / 'unused.db', None)
    supervisor._status['price_action_sources'] = {'coverage_counts': {'fresh': 7, 'expired': 2}}
    supervisor._status['source_request_budget'] = {'local_cap': 12, 'provider_limit_verified': False}
    supervisor._calendar_runner = SimpleNamespace(source_call_gate=SimpleNamespace(
        snapshot=lambda: (_ for _ in ()).throw(AssertionError('GET must not poll collector'))))
    status = supervisor.one_minute_worker_status(nonblocking=True)
    assert status['price_action_sources']['coverage_counts']['fresh'] == 7
    assert status['source_request_budget']['provider_limit_verified'] is False


def test_restart_with_old_source_inflight_does_not_claim_stopped(tmp_path):
    supervisor = OptionRadarSupervisor(tmp_path / 'unused.db', None)
    supervisor.enabled = True
    supervisor._calendar_runner = SimpleNamespace(source_call_gate=SimpleNamespace(
        snapshot=lambda: {'in_flight': True}))
    supervisor._process_lock = SimpleNamespace(acquire=lambda: (_ for _ in ()).throw(
        AssertionError('must not acquire/start another instance')))
    supervisor.start()
    assert supervisor._status['state'] == 'stopping'
    assert supervisor._status['running'] is True


def test_existing_diagnostics_loop_advances_clock_while_source_is_blocked(tmp_path, monkeypatch):
    entered, release, ticked = Event(), Event(), Event()
    def slow_source():
        entered.set()
        release.wait(3)
    source = Thread(target=slow_source)
    supervisor = OptionRadarSupervisor.__new__(OptionRadarSupervisor)
    supervisor.db_path = tmp_path / 'unused.db'
    supervisor._stop = Event()
    supervisor._lock = RLock()
    supervisor._status = {}
    supervisor._calendar_runner = None
    def tick(now):
        assert entered.is_set() and source.is_alive()
        ticked.set()
        supervisor._stop.set()
        return {'state': 'TEST_ONLY_MEASUREMENT', 'precision_verified': False}
    supervisor._clock_monitor = SimpleNamespace(tick=tick)
    supervisor.one_minute_worker_status = lambda: {'state': 'TEST_ONLY'}
    monkeypatch.setattr(RuntimeDiagnostics, 'write', lambda self, value: None)
    diagnostics = Thread(target=supervisor._run_worker_diagnostics)
    source.start()
    try:
        assert entered.wait(1)
        diagnostics.start()
        assert ticked.wait(1)
        diagnostics.join(1)
        assert not diagnostics.is_alive()
        assert supervisor._status['clock_measurement']['state'] == 'TEST_ONLY_MEASUREMENT'
    finally:
        supervisor._stop.set()
        release.set()
        source.join(3)
        if diagnostics.ident is not None:
            diagnostics.join(3)


def test_clock_fault_is_explicit_not_claimed_trusted():
    supervisor = OptionRadarSupervisor.__new__(OptionRadarSupervisor)
    supervisor._lock, supervisor._status = RLock(), {}
    supervisor._calendar_runner = None
    def fail(now):
        raise TimeoutError('TEST_ONLY')
    supervisor._clock_monitor = SimpleNamespace(tick=fail)
    supervisor._tick_clock_measurement(datetime.now(UTC))
    assert supervisor._status['clock_measurement']['state'] == 'MEASUREMENT_UNAVAILABLE'
    assert supervisor._status['clock_measurement']['precision_verified'] is False
