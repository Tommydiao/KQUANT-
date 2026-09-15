import importlib.util
import json
from pathlib import Path

import pytest


def test_control_only_owned_observer_and_idempotent_stop(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / 'scripts/control_hybrid_observer.py'
    spec = importlib.util.spec_from_file_location('observer_control_test', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    run = 'outputs/hybrid_regime_v1/run'
    out = tmp_path / run
    out.mkdir(parents=True)
    manifest = out / 'preregistration.json'
    manifest.write_text(json.dumps({'scope': 'CONTINUOUS_RECEIVER_INTERVAL_RESEARCH', 'execution_enabled': False}))
    assert module.control(run, 'status')['state'] == 'NO_HEARTBEAT_YET'
    for _ in range(2):
        result = module.control(run, 'stop')
        assert result['stop_requested'] and not result['process_termination_confirmed']
    assert (out / 'STOP').exists()
    manifest.write_text(json.dumps({'scope': 'BOUNDED_PUBLIC_OBSERVATION_SERIES', 'execution_enabled': False}))
    (out / 'status.json').write_text(json.dumps({'state': 'RUNNING'}))
    (out / 'report.json').write_text(json.dumps({'state': 'FAILED'}))
    assert module.control(run, 'status')['recorded_status']['state'] == 'FAILED'
    (out / 'manager_failure.json').write_text(json.dumps({'state': 'BLOCKED_STATUS_IO'}))
    report = module.control(run, 'status')
    assert report['recorded_status']['state'] == 'BLOCKED_STATUS_IO'
    assert report['process_liveness_verified'] is False
    manifest.write_text(json.dumps({'scope': 'original_collector', 'execution_enabled': False}))
    with pytest.raises(ValueError, match='isolated'):
        module.control(run, 'stop')
    with pytest.raises(ValueError, match='Independent'):
        module.control('work/original', 'stop')
