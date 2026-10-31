from datetime import UTC, datetime
from types import SimpleNamespace
import json

from kquant import options_price_action_source as actions
from kquant.options_radar_supervisor import OptionRadarSupervisor


def test_metadata_is_bounded_and_omits_raw_and_unapproved_query_fields():
    records = {f'S{i:03}': {'received_at': f'2026-10-12T13:{i % 60:02}:00+00:00',
                           'actual_query': {'symbol': f'S{i:03}.US', 'start_date': '2026-10-09',
                                            'end_date': '2026-10-12', 'secret': 'DO_NOT_EXPORT'},
                           'raw_response': {'huge': 'x' * 10000}, 'reasons': ['X' * 500] * 30}
               for i in range(100)}
    result = actions.observation_summary(records)
    assert len(result['recent_observations']) == 5 and result['omitted_records'] == 95
    assert 'DO_NOT_EXPORT' not in json.dumps(result) and 'raw_response"' not in json.dumps(result)
    assert all(len(row['reasons']) == 8 and len(row['reasons'][0]) == 160 for row in result['recent_observations'])
    assert len(json.dumps(result)) < 12000


def test_capability_failure_preserves_desired_scope_without_inventing_sent_query(tmp_path):
    now = datetime(2026, 10, 12, 13, tzinfo=UTC)
    runner = SimpleNamespace(store=tmp_path / 'sources', _context=lambda: SimpleNamespace())
    result = actions.refresh(runner, now=now, clock=lambda: now, root=tmp_path,
                             reviews={}, scope=[{'symbol': 'TEST', 'identity_status': 'verified'}])
    item = result['recent_observations'][0]
    assert result['requests'] == 0
    assert item['desired_from'] == '2026-10-09' and item['desired_through'] == '2026-10-12'
    assert item['actual_query'] is None and item['query_evidence'] == 'UNCONFIRMED'
    assert item['capability'] and item['reasons']
    supervisor = OptionRadarSupervisor(tmp_path / 'unopened.db', None)
    supervisor._status['price_action_sources'] = result
    supervisor._calendar_runner = SimpleNamespace(source_call_gate=SimpleNamespace(
        snapshot=lambda: (_ for _ in ()).throw(AssertionError('read must not call source'))))
    snapshot = supervisor.one_minute_worker_status(nonblocking=True)
    assert snapshot['price_action_sources']['recent_observations'] == [item]


def test_actual_compact_route_preserves_source_projection_without_get_side_work(tmp_path, monkeypatch):
    from time import monotonic, sleep
    from fastapi.testclient import TestClient
    from kquant.config import KquantConfig
    from kquant.dashboard.app import create_app

    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    monkeypatch.setenv('KQUANT_REQUIRE_API_AUTH', 'true')
    monkeypatch.setenv('KQUANT_API_AUTH_TOKEN', 'TEST_ONLY-source-snapshot')
    monkeypatch.delenv('KQUANT_OPTION_FOUNDATION_ROOT', raising=False)
    now = datetime(2026, 10, 12, 13, tzinfo=UTC)
    source = actions.observation_summary({'TEST': {
        'requested_coverage_from': '2026-10-09', 'requested_coverage_through': '2026-10-12',
        'actual_query': None, 'state': 'CAPABILITY_BLOCKED', 'reasons': ['DATED_INTERFACE_UNAVAILABLE']}})
    app = create_app(config=KquantConfig(db_path=tmp_path / 'business.sqlite3', outputs_dir=tmp_path / 'out'),
                     research_store=tmp_path / 'research.sqlite3', research_clock=lambda: now,
                     manual_store=tmp_path / 'manual.sqlite3')
    snapshots = app.state.research_http_snapshots
    reads = []
    def load(*args, **kwargs):
        reads.append('background')
        return {'session': '2026-10-12', 'evaluations': [], 'candidates': []}
    monkeypatch.setattr('kquant.status_worker.load_opening_trend', load)
    monkeypatch.setattr('kquant.status_worker.load_current_cards', load)
    snapshots.worker = lambda: {'session': '2026-10-12', 'price_action_sources': source,
                                'source_request_budget': {'used': 0, 'local_cap': 12},
                                'source_call': {'in_flight': False}}
    snapshots.observer = lambda: {'state': 'TEST_ONLY', 'enforced': False}
    snapshots.strategy_availability = lambda strategy: {'enabled': strategy == 'opening_momentum'}
    client = TestClient(app)
    endpoint = '/api/options/one-minute/status?research_strategy=opening_momentum&compact=true'
    headers = {'X-KQUANT-API-TOKEN': 'TEST_ONLY-source-snapshot'}
    try:
        assert client.get(endpoint).status_code == 401
        limit = monotonic() + 5
        response = None
        while monotonic() < limit:
            snapshots.tick()
            response = client.get(endpoint, headers=headers)
            if response.status_code == 200:
                break
            sleep(.02)
        assert response is not None and response.status_code == 200
        worker = response.json()['worker']
        assert worker['price_action_sources'] == source
        assert worker['source_request_budget']['used'] == 0
        assert worker['source_call']['in_flight'] is False
        count = len(reads)
        for _ in range(3):
            assert client.get(endpoint, headers=headers).json()['worker']['price_action_sources'] == source
        assert len(reads) == count
    finally:
        client.close()
        snapshots.close()


def test_source_only_change_notifies_but_age_only_refresh_does_not():
    from copy import deepcopy
    from time import monotonic, sleep
    from kquant.research_http_snapshots import ResearchHttpSnapshots

    now = datetime(2026, 10, 12, 13, tzinfo=UTC)
    source = {'observation_revision': 'first', 'coverage_counts': {'fresh': 0, 'expired': 1},
              'oldest_wait_seconds': 1}
    notifications = []
    feed = ResearchHttpSnapshots(lambda: {'session': '2026-10-12'},
        lambda strategy, kind, worker: {'session': '2026-10-12',
            **({'worker': {'price_action_sources': deepcopy(source)}} if kind == 'compact' else {})},
        lambda: {'state': 'TEST_ONLY', 'enforced': False}, clock=lambda: now,
        on_complete=notifications.append,
        strategy_availability=lambda strategy: {'enabled': strategy == 'opening_momentum'})
    def collect():
        cache = feed.caches['opening_momentum', 'compact']
        previous = cache.as_of
        # Force a normal TTL refresh, not invalidation (which itself changes the watermark).
        cache.completed = 0
        cache.attempted = float('-inf')
        limit = monotonic() + 3
        while monotonic() < limit:
            feed.tick()
            if cache.as_of != previous and cache.future is None:
                return
            sleep(.01)
        raise AssertionError('BACKGROUND_REFRESH_DID_NOT_COMPLETE')
    try:
        collect()
        count = len(notifications)
        source['oldest_wait_seconds'] = 2
        collect()
        assert len(notifications) == count
        source['observation_revision'] = 'second'
        source['coverage_counts'] = {'fresh': 1, 'expired': 0}
        collect()
        assert len(notifications) == count + 1
        assert feed.read('opening_momentum', 'compact')['worker']['price_action_sources'] == source
    finally:
        feed.close()
