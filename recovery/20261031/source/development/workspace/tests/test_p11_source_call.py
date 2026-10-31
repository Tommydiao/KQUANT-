from threading import Event
from time import monotonic
from datetime import UTC, datetime
from types import SimpleNamespace
from pathlib import Path
import json

import pytest

from kquant.options_source_call import SourceCallGate, SourceCallBusy, SourceCallTimeout


def test_timeout_does_not_replace_inflight_or_return_late_result():
    gate = SourceCallGate(timeout=.02)
    release, finished = Event(), Event()
    def blocked():
        release.wait(2)
        finished.set()
        return 'late'
    started = monotonic()
    try:
        with pytest.raises(SourceCallTimeout):
            gate.call(blocked)
        assert monotonic() - started < .5
        assert gate.snapshot()['in_flight']
        assert not gate.snapshot()['transport_cancellation_proven']
        with pytest.raises(SourceCallBusy):
            gate.call(lambda: pytest.fail('duplicate request'))
        release.set()
        assert finished.wait(1)
        gate._thread.join(1)
        assert gate.call(lambda: 'fresh') == 'fresh'
    finally:
        release.set()
        assert not gate.close()['in_flight']


def test_close_latches_without_claiming_stuck_transport_was_cancelled():
    gate, release = SourceCallGate(timeout=.02), Event()
    try:
        with pytest.raises(SourceCallTimeout):
            gate.call(lambda: release.wait(2))
        assert gate.close()['in_flight']
        with pytest.raises(SourceCallBusy):
            gate.call(lambda: None)
    finally:
        release.set()
        gate._thread.join(1)
        assert not gate.close()['in_flight']


def test_actual_calendar_runner_defers_inflight_and_discards_late_pages(tmp_path, monkeypatch):
    from kquant.option_calendar_source import CalendarSourceRunner
    from kquant import options_two_hour_data
    monkeypatch.setattr(options_two_hour_data, 'universe', lambda _: {
        'scope_hash': 'TEST_ONLY', 'items': [{'symbol': 'AAPL', 'provider_symbol': 'AAPL.US',
                                           'identity_status': 'verified'}]})
    release, calls = Event(), []

    def request(verb, path):
        calls.append((verb, path))
        release.wait(2)
        return {'list': [], 'next_date': ''}

    runner = CalendarSourceRunner(tmp_path / 'not-opened.sqlite3', store=tmp_path / 'sources',
                                  context=SimpleNamespace(request=request))
    runner.source_call_gate = SourceCallGate(timeout=.02)
    try:
        first = runner.refresh(now=datetime(2026, 10, 12, 13, tzinfo=UTC))
        assert first['calendar_requests'] == 1
        assert len(calls) == 1
        manifest = json.loads((Path(first['run_ref']) / 'manifest.json').read_text())
        issues = [item for row in manifest['categories'].values() for item in row['issues']]
        assert issues.count('SOURCE_REQUEST_STILL_IN_FLIGHT') == 5
        assert 'LOCAL_CALENDAR_REQUEST_CAP' not in issues
        assert first['source_complete_categories'] == 0 and not first['trade_eligible']
        second = runner.refresh(now=datetime(2026, 10, 12, 13, 1, tzinfo=UTC))
        assert second['calendar_requests'] == 0 and len(calls) == 1
        release.set()
        runner.source_call_gate._thread.join(1)
        # Completion cannot mutate already archived failed observations.
        assert first['source_complete_categories'] == second['source_complete_categories'] == 0
        third = runner.refresh(now=datetime(2026, 10, 12, 13, 2, tzinfo=UTC))
        assert third['calendar_requests'] == 6 and len(calls) == 7
        assert not third['trade_eligible']
    finally:
        release.set()
        assert not runner.source_call_gate.close()['in_flight']
