from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
import sys
from threading import Barrier, Lock
from time import sleep
from types import SimpleNamespace

import pytest


def isolated_clock(monkeypatch, loader):
    name = 'kquant._singleflight_test_clock'
    path = Path(__file__).parents[1] / 'kquant/market_clock.py'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setitem(sys.modules, 'exchange_calendars', SimpleNamespace(get_calendar=loader))
    spec.loader.exec_module(module)
    return module


def test_cold_concurrent_calendar_is_constructed_once(monkeypatch):
    calls = []
    guard = Lock()
    expected = object()

    def load(name):
        with guard:
            calls.append(name)
        sleep(.05)
        return expected

    clock = isolated_clock(monkeypatch, load)
    ready = Barrier(8)

    def read(_):
        ready.wait(timeout=5)
        return clock._calendar()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(read, range(8)))
    assert calls == ['XNYS']
    assert all(result is expected for result in results)
    assert clock._calendar() is expected
    assert len(calls) == 1


def test_failed_calendar_load_is_not_cached(monkeypatch):
    calls = []
    expected = object()

    def load(name):
        calls.append(name)
        if len(calls) == 1:
            raise RuntimeError('TEST_ONLY_CALENDAR_LOAD_FAILURE')
        return expected

    clock = isolated_clock(monkeypatch, load)
    with pytest.raises(RuntimeError, match='TEST_ONLY_CALENDAR_LOAD_FAILURE'):
        clock._calendar()
    assert clock._calendar() is expected
    assert clock._calendar() is expected
    assert calls == ['XNYS', 'XNYS']
