import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('fault', [None, 'queue_schema', 'opening_file'])
def test_real_supervisor_cold_start_and_init_failure(tmp_path, fault):
    out = tmp_path / ('TEST_ONLY-' + (fault or 'normal'))
    command = [sys.executable, str(ROOT/'scripts/check_p12_bootstrap.py'), '--out', str(out), '--seconds', '11']
    if fault:
        command += ['--fault', fault]
    run = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stdout + run.stderr
    report = json.loads((out/'report.json').read_text())
    assert report['actual_supervisor_start'] and report['actual_worker_init_run']
    assert not report['alive_threads'] and not report['forbidden_sibling_exists']
    assert report['final'].get('cleanup_complete', True)
    if fault:
        assert report['final']['state'] == 'FAILED_INIT'
        assert 'error_frames' in report['final']
        assert not report['final'].get('first_loop_at')


def test_failure_status_is_not_erased_and_created_thread_is_not_ready():
    from datetime import UTC, datetime
    from kquant.research_runtime_health import worker_health
    now = datetime.now(UTC)
    failed = worker_health({'state': 'FAILED_INIT', 'error_id': 'fixture'}, alive=False, now=now)
    assert failed['state'] == 'FAILED_INIT'
    assert not failed['research_ready']
    created = worker_health({'state': 'NOT_STARTED', 'stage_started_at': now.isoformat()}, alive=True, now=now)
    assert not created['research_ready']
    ready = worker_health({'state': 'WAIT_MARKET', 'first_loop_at': now.isoformat(),
                           'stage_started_at': now.isoformat()}, alive=True, now=now)
    assert ready['research_ready']


def test_lifecycle_writes_data_root_not_code_root(tmp_path):
    script = ROOT/'scripts/FoundationLifecycle.ps1'
    code_root = tmp_path/'code'
    data_root = tmp_path/'data'
    code_root.mkdir()
    data_root.mkdir()
    code = f"""$ErrorActionPreference='Stop'
$Root='{code_root}'
$foundationRoot='{data_root}'
$script:LaunchStamp='TEST_ONLY'
. '{script}'
Write-FoundationLifecycle 'STARTING' 'TEST_ONLY'
"""
    result = subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', code], capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    events = list(data_root.glob('lifecycle.*.jsonl'))
    assert len(events) == 1
    assert json.loads(events[0].read_text())['reason'] == 'TEST_ONLY'
    assert not list(code_root.iterdir())


def test_cache_invalidation_alone_does_not_repeat_market_notification():
    from kquant.research_http_snapshots import ResearchHttpSnapshots
    notifications = []
    snapshots = ResearchHttpSnapshots(lambda: {'research_ready': True},
        lambda strategy, kind, worker: {'summary': {'completed': 0}},
        lambda: {'state': 'RUNNING'}, on_complete=notifications.append)
    try:
        for _ in range(10):
            snapshots.tick()
            time.sleep(.02)
        assert notifications
        notifications.clear()
        snapshots.invalidate('opening_momentum')
        for _ in range(10):
            snapshots.tick()
            time.sleep(.02)
        assert notifications == []
        assert snapshots.read('opening_momentum', 'current')['snapshot']['state'] == 'FRESH'
    finally:
        snapshots.close()


def test_dead_worker_cannot_keep_current_candidate_actionable():
    from kquant.research_http_snapshots import ResearchHttpSnapshots
    snapshots = ResearchHttpSnapshots(lambda: {'research_ready': False, 'state': 'FAILED_INIT'},
        lambda strategy, kind, worker: {'candidates': [{'evaluation_id': 'TEST_ONLY'}]},
        lambda: {'state': 'RUNNING'})
    try:
        for _ in range(10):
            snapshots.tick()
            time.sleep(.02)
        result = snapshots.read('opening_momentum', 'current')
        assert result['snapshot']['error_type'] == 'RESEARCH_WORKER_NOT_READY'
        assert result['candidates'] == []
        assert result['service_observation']['research_worker']['state'] == 'FAILED_INIT'
    finally:
        snapshots.close()
