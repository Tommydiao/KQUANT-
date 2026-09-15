"""Ownership/duration boundaries for the independent public observation CLI."""
import importlib.util
from pathlib import Path
import sys

import pytest


@pytest.fixture
def runner(monkeypatch, tmp_path):
    scripts = Path(__file__).resolve().parents[1] / 'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location('continuous_test_runner', scripts / 'run_hybrid_continuous_observer.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    return module


@pytest.mark.parametrize('duration', ['0', '29', '259201'])
def test_duration_rejected_before_creating_outputs(runner, monkeypatch, tmp_path, duration):
    monkeypatch.setattr(sys, 'argv', ['observer', '--output', 'outputs/hybrid_regime_v1/test', '--seconds', duration])
    with pytest.raises(ValueError, match='duration'):
        runner.main()
    assert not (tmp_path / 'outputs').exists()


def test_single_owner_lock_covers_run_and_prevents_second_output(runner, monkeypatch, tmp_path):
    output = 'outputs/hybrid_regime_v1/test'
    monkeypatch.setattr(sys, 'argv', ['observer', '--output', output, '--seconds', '86400'])
    lock = tmp_path / 'work/hybrid_delivery/continuous_public_observer.lock'

    async def isolated(out, seconds):
        assert out == tmp_path / output and seconds == 86400
        with pytest.raises(OSError):
            with runner._process_lock(lock):
                pytest.fail('Second owner acquired active lock')
        return 0

    monkeypatch.setattr(runner, 'observe', isolated)
    assert runner.main() == 0
    with runner._process_lock(lock):
        pass
    with pytest.raises(FileExistsError):
        runner.main()


def test_output_cannot_target_original_storage(runner, monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'argv', ['observer', '--output', 'work/original', '--seconds', '30'])
    with pytest.raises(ValueError, match='Independent'):
        runner.main()
    assert not (tmp_path / 'work').exists()
