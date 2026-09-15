import datetime
import importlib.util
from pathlib import Path
import pytest


def test_draw_callback_honors_deadline_without_loading_model(monkeypatch):
    path = Path(__file__).resolve().parents[1]/'scripts/fit_multifactor_population_dev.py'
    spec = importlib.util.spec_from_file_location('population_deadline_check', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    now = datetime.datetime.now(datetime.timezone.utc)
    monkeypatch.setattr(module, 'DEADLINE', now-datetime.timedelta(seconds=1))
    with pytest.raises(module.DeadlineReached):
        module.check_deadline(trace=None, draw=None)
    monkeypatch.setattr(module, 'DEADLINE', now+datetime.timedelta(hours=1))
    module.check_deadline(trace=None, draw=None)
