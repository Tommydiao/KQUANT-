import datetime
import importlib.util
from pathlib import Path

import pytest


def module():
    path = Path(__file__).resolve().parents[1]/'scripts/run_multifactor_mc_dev.py'
    spec = importlib.util.spec_from_file_location('mc_runner', path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_no_implicit_historical_deadline():
    m = module()
    assert m.parse_deadline(None) is None
    assert m.deadline_reached(None) is False


def test_explicit_deadlines_and_timezone():
    m = module()
    assert m.deadline_reached(m.parse_deadline('2000-01-01T00:00:00Z')) is True
    assert m.deadline_reached(m.parse_deadline('2999-01-01T00:00:00+00:00')) is False
    assert m.parse_deadline('2026-09-09T08:00:00+08:00') == datetime.datetime(2026,9,9,tzinfo=datetime.timezone.utc)
    with pytest.raises(ValueError, match='timezone'):
        m.parse_deadline('2026-09-09T00:00:00')
