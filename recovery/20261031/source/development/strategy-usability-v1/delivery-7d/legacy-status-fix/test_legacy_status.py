from datetime import UTC, datetime, timedelta
import json
import random
import sqlite3

import pytest

from overlay import install

original, revised, worker = install()
from kquant.options_one_minute_status import evaluation_view, validate_history_sessions


@pytest.mark.parametrize('scope', [None, 'scope', 'other'])
@pytest.mark.parametrize('seed', [2, 7, 41])
def test_full_legacy_response_equivalence(tmp_path, scope, seed):
    path = tmp_path/'minute.sqlite3'
    original.initialize(path)
    policy = original.load_policy()
    now = datetime(2026, 10, 16, 14, 0, tzinfo=UTC)
    rng = random.Random(seed)
    with sqlite3.connect(path) as connection:
        for symbol in ('AAA', 'BBB', 'CCC'):
            connection.execute('INSERT INTO one_minute_prewarm VALUES (?,?,?,?,?,?)',
                ('2026-10-16', symbol, 'READY', None, now.isoformat(), '{}'))
        for index in range(500):
            symbol, right = rng.choice(('AAA', 'BBB', 'CCC')), rng.choice(('CALL', 'PUT'))
            bar = (now-timedelta(minutes=rng.choice((1, 2, 3)))).isoformat()
            created = (now+timedelta(seconds=rng.randrange(8))).isoformat()
            state = rng.choice(('NO_TRIGGER', 'INCOMPLETE', 'NUMERIC_PASS', 'NUMERIC_PASS_EVENT_PENDING'))
            payload = {'evaluation_id': str(index), 'symbol': symbol, 'right': right,
                'policy_hash': rng.choice((policy['policy_hash'], 'previous')),
                'scope_hash': rng.choice(('scope', 'other')), 'state': state,
                'factor_evidence': {'m': .5} if state != 'INCOMPLETE' else {},
                'deadline_at': (now+timedelta(seconds=rng.choice((-2, 2)))).isoformat()}
            connection.execute('INSERT INTO one_minute_evaluations VALUES (?,?,?,?,?,?,?,?,?)',
                (str(index), str(index), '2026-10-16', symbol, right, bar, state, json.dumps(payload), created))
    assert revised.status(path, now=now, scope_hash=scope) == original.status(path, now=now, scope_hash=scope)


def test_empty_status_and_unrelated_session(tmp_path):
    path = tmp_path/'minute.sqlite3'
    original.initialize(path)
    now = datetime(2026, 10, 17, 14, tzinfo=UTC)
    assert revised.status(path, now=now) == original.status(path, now=now)


def test_many_same_bar_revisions_decode_only_latest_match(tmp_path, monkeypatch):
    path = tmp_path/'minute.sqlite3'
    revised.initialize(path)
    with sqlite3.connect(path) as db:
        for index in range(2000):
            payload = {'evaluation_id': str(index), 'policy_hash': 'p', 'scope_hash': 's'}
            db.execute('INSERT INTO one_minute_evaluations VALUES (?,?,?,?,?,?,?,?,?)',
                (str(index), str(index), '2026-10-16', 'AAA', 'CALL', '13:35',
                 'INCOMPLETE', json.dumps(payload), f'{index:06}'))
        calls = []
        decode = json.loads
        def counted(raw):
            calls.append(1)
            return decode(raw)
        monkeypatch.setattr(json, 'loads', counted)
        result = evaluation_view(db, session='2026-10-16', policy_hash='p', scope_hash='s')
        assert result['bar_rows'][0]['evaluation_id'] == '1999'
        assert result['counts']['INCOMPLETE'] == 2000
        assert len(calls) == 1


def test_single_metadata_pass_decodes_only_needed_rows(tmp_path):
    path = tmp_path/'minute.sqlite3'
    original.initialize(path)
    with sqlite3.connect(path) as connection:
        for index in range(1000):
            # Old irrelevant malformed evidence must not be parsed by a summary query.
            payload = '{}' if index == 999 else 'invalid-not-current-json'
            connection.execute('INSERT INTO one_minute_evaluations VALUES (?,?,?,?,?,?,?,?,?)',
                (str(index), str(index), '2026-10-16', 'AAA', 'CALL', f'{index:06}',
                 'INCOMPLETE', payload, f'{index:06}'))
        statements = []
        connection.set_trace_callback(statements.append)
        result = evaluation_view(connection, session='2026-10-16', policy_hash='p', scope_hash=None)
        assert result['counts'] == {'INCOMPLETE': 1000}
        assert result['last_bar_end'] == result['last_evaluation_at'] == '000999'
        assert len(result['rows']) == 1
        assert len(statements) == 2
        assert all('json_extract' not in statement.lower() for statement in statements)


@pytest.mark.parametrize('day', ['2026-10-16', '2026-10-17', '2026-11-26', '2026-11-27', '2026-11-02'])
def test_background_calendar_context_matches_existing_policy(day):
    now = datetime.fromisoformat(day+'T14:30:00+00:00')
    value = worker.one_minute_history_context(now)
    from kquant.options_two_hour_data import sessions_before
    assert value['sessions'] == sessions_before(now.date(), original.load_policy()['history_sessions'])
    assert value['calendar_source'] == 'exchange_calendars:XNYS'


@pytest.mark.parametrize('values', [None, [], ['2026-10-17'], ['2026-10-15']*2,
                                   ['2026-10-15', '2026-10-14'], ['bad', 'date']])
def test_invalid_calendar_context_rejected(values):
    with pytest.raises((ValueError, TypeError)):
        validate_history_sessions(values, session='2026-10-16', count=2)


def test_old_bar_revision_does_not_replace_maximum_bar(tmp_path):
    path = tmp_path/'minute.sqlite3'
    original.initialize(path)
    with sqlite3.connect(path) as connection:
        for index, bar, created, scope in [(1, '09:40', '10:02', 's'), (2, '09:45', '09:45', 's'),
                                            (3, '09:45', '10:03', 'other')]:
            payload = {'evaluation_id': str(index), 'policy_hash': 'p', 'scope_hash': scope}
            connection.execute('INSERT INTO one_minute_evaluations VALUES (?,?,?,?,?,?,?,?,?)',
                (str(index), str(index), '2026-10-16', 'AAA', 'CALL', bar, 'NO_TRIGGER', json.dumps(payload), created))
        result = evaluation_view(connection, session='2026-10-16', policy_hash='p', scope_hash='s')
        assert result['last_bar_end'] == '09:45'
        assert result['last_evaluation_at'] == '10:03'
        assert result['rows'][0]['evaluation_id'] == '3'
        assert result['bar_rows'][0]['evaluation_id'] == '2'


def test_preparation_failures_count_as_failures(monkeypatch):
    def fail(now):
        raise FileNotFoundError('TEST_ONLY_MISSING_POLICY')
    monkeypatch.setattr(worker, 'one_minute_history_context', fail)
    before = dict(worker._attempt_counts)
    with pytest.raises(worker.StatusQueryFailure) as captured:
        worker.load_one_minute('unused')
    assert worker._attempt_counts['attempts'] == before['attempts'] + 1
    assert worker._attempt_counts['failures'] == before['failures'] + 1
    assert captured.value.diagnostic['query_transport']['query_lane'] == 'one_minute:status'


@pytest.mark.parametrize('change', ['stale', 'future', 'policy', 'calendar', 'count'])
def test_child_rejects_invalid_handoff(tmp_path, monkeypatch, change):
    from kquant import options_two_hour_data
    main = tmp_path/'main.sqlite3'
    main.touch()
    monkeypatch.setattr(options_two_hour_data, 'universe', lambda path: {'scope_hash': 'TEST_ONLY'})
    context = worker.one_minute_history_context()
    if change in {'stale', 'future'}:
        context['prepared_at'] = (datetime.now(UTC)+timedelta(seconds=30 if change == 'future' else -30)).isoformat()
    elif change == 'policy':
        context['policy_hash'] = 'other'
    elif change == 'calendar':
        context['calendar_source'] = 'weekdays_are_not_exchange_sessions'
    else:
        context['sessions'] = []
    with pytest.raises(ValueError, match='STATUS_HISTORY_CONTEXT'):
        worker.query(main, history_context=context)


def test_actual_app_background_legacy_reader_with_separate_stores(tmp_path, monkeypatch):
    import os
    import sys
    import time
    from pathlib import Path
    from overlay import BASE, HERE
    sys.path.insert(0, str(HERE/'tools'))
    from bootstrap import activate
    activate()
    from fastapi.testclient import TestClient
    from kquant.config import KquantConfig
    from kquant.dashboard.app import create_app
    from kquant.options_opening_trend_store import initialize as research_initialize
    assert Path(sys.modules['kquant.dashboard.app'].__file__).is_relative_to(HERE/'patches')
    for key in tuple(os.environ):
        if key.startswith('KQUANT_'):
            monkeypatch.delenv(key)
    monkeypatch.setenv('KQUANT_REALTIME_SUPERVISOR_ENABLED', 'false')
    monkeypatch.setenv('KQUANT_OPTION_RADAR_ENABLED', 'false')
    monkeypatch.setenv('KQUANT_WORKSPACE_LOGIN_ENABLED', 'false')
    monkeypatch.setenv('KQUANT_REQUIRE_API_AUTH', 'true')
    monkeypatch.setenv('KQUANT_API_AUTH_TOKEN', 'TEST_ONLY_LEGACY_API_TOKEN')
    monkeypatch.setenv('KQUANT_TEST_LEGACY_OVERLAY', str(HERE))
    monkeypatch.setenv('PYTHONPATH', str(HERE/'tools')+os.pathsep+str(BASE))
    minute = tmp_path/'epoch/minute.sqlite3'
    research = tmp_path/'research/other.sqlite3'
    original.initialize(minute)
    research_initialize(research)
    clock = datetime(2026, 10, 15, 14, 0, tzinfo=UTC)
    with sqlite3.connect(minute) as connection:
        connection.execute('INSERT INTO one_minute_prewarm VALUES (?,?,?,?,?,?)',
            ('2026-10-15', 'TEST_ONLY', 'PENDING', 'TEST_ONLY', clock.isoformat(), '{}'))
    app = create_app(config=KquantConfig(db_path=tmp_path/'main.sqlite3', outputs_dir=tmp_path/'outputs'),
        research_store=research, manual_store=minute, minute_status_store=minute, research_clock=lambda: clock)
    assert app.state.research_http_snapshots.on_tick is not None
    assert app.state.main_store_concurrency['journal_mode'] == 'wal'
    with TestClient(app) as client:
        assert client.get('/api/options/one-minute/status').status_code == 401
        deadline = time.monotonic()+12
        while time.monotonic() < deadline:
            response = client.get('/api/options/one-minute/status',
                headers={'X-KQUANT-API-TOKEN': 'TEST_ONLY_LEGACY_API_TOKEN'})
            if response.status_code == 200:
                break
            assert response.status_code == 503
            time.sleep(.2)
        assert response.status_code == 200, response.text
        value = response.json()
        assert value['session'] == '2026-10-15'
        assert value['summary']['registered_symbols'] == 1
        assert value['prewarm'][0]['symbol'] == 'TEST_ONLY'
        assert value['query_transport']['outcome'] == 'SUCCESS'
        assert value['query_transport']['child_reaped'] is True
        assert value['history_context_ms'] >= 0
