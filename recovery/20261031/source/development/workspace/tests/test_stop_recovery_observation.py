from copy import deepcopy
from datetime import UTC, datetime, timedelta
from kquant.options_service_observation import adjudicate

NOW = datetime(2026, 10, 14, 14, tzinfo=UTC)


def runtime():
    launcher = {'pid': 10, 'created_at': (NOW - timedelta(hours=1)).isoformat(), 'executable': 'pwsh.exe'}
    back = {'pid': 11, 'created_at': launcher['created_at'], 'executable': 'python.exe'}
    gate = {**back, 'pid': 12}
    manifest = {'launcher_pid': 10, 'launcher_identity': launcher, 'checked_at': NOW.isoformat(),
        'run_session_id': 'run-1', 'state': 'RUNNING', 'health_verified': True,
        'listeners': [{'port': 8001, 'pid': 11, 'identity': back, 'command_verified': True},
                      {'port': 8020, 'pid': 12, 'identity': gate, 'command_verified': True}]}
    processes = {x['pid']: {**x, 'alive': True} for x in (launcher, back, gate)}
    ports = [{'port': 8001, 'pid': 11}, {'port': 8020, 'pid': 12}]
    return manifest, processes, ports


def test_reboot_distinct_from_unknown_original_disappearance():
    m, p, _ = runtime()
    p[10] = {'pid': 10, 'alive': False}
    result = adjudicate(m, p, [], now=NOW,
        system_boot={'state': 'VERIFIED', 'started_at': (NOW - timedelta(minutes=10)).isoformat()})
    assert result['state'] == 'STOPPED'
    assert result['recovery_reason'] == 'PREVIOUS_BOOT_NOT_RESTARTED'
    assert result['exit_reason'] == 'UNKNOWN'
    assert result['reported_state'] == 'RUNNING'
    assert result['run_session_id'] == 'run-1'


def test_same_boot_stop_keeps_original_cause_unknown():
    m, p, _ = runtime()
    p[10] = {'pid': 10, 'alive': False}
    result = adjudicate(m, p, [], now=NOW,
        system_boot={'state': 'VERIFIED', 'started_at': (NOW - timedelta(days=1)).isoformat()})
    assert result['state'] == 'STOPPED'
    assert result['recovery_reason'] is None
    assert result['exit_reason'] == 'UNKNOWN'


def test_fresh_permissions_failure_never_reports_running():
    m, p, ports = runtime()
    p[10] = {'pid': 10, 'alive': None, 'error': 'WIN32_5'}
    assert adjudicate(m, p, ports, now=NOW)['state'] != 'RUNNING'


def test_stale_live_process_or_pid_reuse_never_reports_running():
    m, p, ports = runtime()
    m['checked_at'] = (NOW - timedelta(seconds=31)).isoformat()
    assert adjudicate(m, p, ports, now=NOW)['state'] == 'UNKNOWN_STALE'
    m['checked_at'] = NOW.isoformat()
    p[10]['created_at'] = NOW.isoformat()
    assert adjudicate(m, p, ports, now=NOW)['state'] == 'DEGRADED'


def test_valid_identity_still_requires_recorded_health():
    m, p, ports = runtime()
    assert adjudicate(m, p, ports, now=NOW)['state'] == 'RUNNING'
    m['health_verified'] = False
    assert adjudicate(m, p, ports, now=NOW)['state'] == 'DEGRADED'


def test_boot_probe_cached_and_bounded(monkeypatch):
    from kquant import options_service_observation as obs
    from types import SimpleNamespace
    calls = []
    monkeypatch.setenv('KQUANT_LAUNCHER_HOST', r'C:\trusted\pwsh.exe')
    obs.system_boot_identity.cache_clear()
    def probe(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout='2026-10-14T13:15:46.5000000Z\n')
    monkeypatch.setattr(obs.subprocess, 'run', probe)
    try:
        assert obs.system_boot_identity()['state'] == 'VERIFIED'
        assert obs.system_boot_identity()['state'] == 'VERIFIED'
        assert len(calls) == 1
        assert calls[0][1]['timeout'] == 4
        assert calls[0][0][0] == r'C:\trusted\pwsh.exe'
    finally:
        obs.system_boot_identity.cache_clear()


def test_boot_host_rejects_fault_drive_without_probe(monkeypatch):
    from kquant import options_service_observation as obs
    obs.system_boot_identity.cache_clear()
    monkeypatch.setenv('KQUANT_LAUNCHER_HOST', r'F:\unavailable\pwsh.exe')
    monkeypatch.setattr(obs.subprocess, 'run', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('probe forbidden')))
    try:
        assert obs.system_boot_identity()['error_type'] == 'BOOT_HOST_UNCONFIRMED'
    finally:
        obs.system_boot_identity.cache_clear()
