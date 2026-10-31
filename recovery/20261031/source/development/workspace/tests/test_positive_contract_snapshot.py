"""Synthetic pipeline -> SQLite -> actual background snapshot lifecycle.

Not browser, market latency, or production approval evidence.
"""
from datetime import timedelta
from time import monotonic, sleep

from test_r58_positive_chain import prepare
from kquant import options_opening_momentum as model
from kquant import options_opening_trend_store as store
from kquant.options_opening_trend_pipeline import step
from kquant.research_http_snapshots import ResearchHttpSnapshots
from kquant.status_snapshot import SnapshotUnavailable


def test_persisted_qualified_contract_reaches_snapshot_and_expires_without_refresh(tmp_path, monkeypatch):
    args, original, services, _ = prepare(tmp_path, monkeypatch)
    clock = [args["now"]]
    path = tmp_path / "TEST_ONLY-positive.sqlite3"
    store.initialize(path)
    store.persist([original], path)
    job = {"evaluation": original, "progress": {}}
    for _ in range(6):
        progress, _, revision = step(job, services, clock=lambda: clock[0])
        job["progress"] = progress
    assert revision["state"] == "QUALIFIED"
    store.append_revision(original["evaluation_id"], revision, path)

    reads = []
    def load(strategy, kind, worker):
        reads.append((strategy, kind))
        return store.current_cards(path=path, session=original["session"], scope_hash="scope",
                                   now=clock[0], policy=model.load_policy())

    snapshots = ResearchHttpSnapshots(
        lambda: {"session": original["session"], "scope_hash": "scope"},
        load, lambda: {"state": "TEST_ONLY", "enforced": False}, clock=lambda: clock[0],
        strategy_availability=lambda strategy: {"enabled": strategy == "opening_momentum"})
    try:
        limit = monotonic() + 3
        payload = None
        while monotonic() < limit:
            snapshots.tick()
            try:
                payload = snapshots.read("opening_momentum", "current")
                if payload.get("candidates"):
                    break
            except SnapshotUnavailable:
                pass
            sleep(.01)
        assert payload and len(payload["candidates"]) == 1
        card = payload["candidates"][0]
        assert card["evaluation_id"] == original["evaluation_id"]
        assert card["contract_id"] == "TEST261006C105000.US"
        assert card["deadline_at"] == original["deadline_at"]
        valid_until = card["current_eligibility"]["valid_until"]
        count = len(reads)
        clock[0] += timedelta(seconds=3)
        # Read-time expiry must work even if the background producer stops.
        assert snapshots.read("opening_momentum", "current")["candidates"] == []
        assert len(reads) == count
        assert card["current_eligibility"]["valid_until"] == valid_until
    finally:
        snapshots.close()


def test_actual_authenticated_current_route_serves_pipeline_contract_then_expires(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from kquant.config import KquantConfig
    from kquant.dashboard.app import create_app
    args, original, services, _ = prepare(tmp_path, monkeypatch)
    clock = [args['now']]
    path = tmp_path / 'TEST_ONLY-http-research.sqlite3'
    store.initialize(path)
    store.persist([original], path)
    job = {'evaluation': original, 'progress': {}}
    for _ in range(6):
        progress, _, revision = step(job, services, clock=lambda: clock[0])
        job['progress'] = progress
    assert revision['state'] == 'QUALIFIED'
    store.append_revision(original['evaluation_id'], revision, path)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    monkeypatch.setenv('KQUANT_REQUIRE_API_AUTH', 'true')
    monkeypatch.setenv('KQUANT_API_AUTH_TOKEN', 'TEST_ONLY-current-route')
    monkeypatch.delenv('KQUANT_OPTION_FOUNDATION_ROOT', raising=False)
    app = create_app(config=KquantConfig(db_path=tmp_path / 'TEST_ONLY-business.sqlite3', outputs_dir=tmp_path / 'out'),
                     research_store=path, research_clock=lambda: clock[0],
                     manual_store=tmp_path / 'TEST_ONLY-manual.sqlite3')
    snapshots = app.state.research_http_snapshots
    snapshots.worker = lambda: {'session': original['session'], 'scope_hash': 'scope'}
    snapshots.observer = lambda: {'state': 'TEST_ONLY', 'enforced': False}
    snapshots.strategy_availability = lambda strategy: {'enabled': strategy == 'opening_momentum'}
    snapshots.loader = lambda strategy, kind, worker: store.current_cards(
        path=path, session=original['session'], scope_hash='scope', now=clock[0], policy=model.load_policy())
    client = TestClient(app)
    endpoint = '/api/options/opening-trend/current?research_strategy=opening_momentum'
    try:
        assert client.get(endpoint).status_code == 401
        headers = {'X-KQUANT-API-TOKEN': 'TEST_ONLY-current-route'}
        limit = monotonic() + 3
        result = None
        while monotonic() < limit:
            snapshots.tick()
            result = client.get(endpoint, headers=headers)
            if result.status_code == 200 and result.json().get('candidates'):
                break
            sleep(.01)
        assert result is not None and result.status_code == 200
        card = result.json()['candidates'][0]
        assert card['evaluation_id'] == original['evaluation_id']
        assert card['contract_id'] == 'TEST261006C105000.US'
        assert card['deadline_at'] == original['deadline_at']
        clock[0] += timedelta(seconds=3)
        expired = client.get(endpoint, headers=headers)
        assert expired.status_code == 200 and expired.json()['candidates'] == []
        assert client.get(endpoint).status_code == 401
    finally:
        client.close()
        snapshots.close()
