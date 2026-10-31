"""Actual TCP disconnect must release its subscriber without a keepalive wait."""
from time import monotonic, sleep

import httpx

from kquant.config import KquantConfig
from kquant.dashboard.app import create_app
from test_positive_contract_tcp import tcp_server


def test_tcp_disconnect_releases_alert_subscription_promptly(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    monkeypatch.setenv('KQUANT_REQUIRE_API_AUTH', 'true')
    monkeypatch.setenv('KQUANT_API_AUTH_TOKEN', 'TEST_ONLY-stream')
    monkeypatch.delenv('KQUANT_OPTION_FOUNDATION_ROOT', raising=False)
    app = create_app(config=KquantConfig(db_path=tmp_path / 'business.sqlite3', outputs_dir=tmp_path / 'out'),
                     research_store=tmp_path / 'research.sqlite3', manual_store=tmp_path / 'manual.sqlite3')
    hub = app.state.alert_hub
    try:
        with tcp_server(app, lifespan='off') as address:
            with httpx.Client(timeout=2) as client:
                with client.stream('GET', address + '/api/alerts/stream',
                                   headers={'X-KQUANT-API-TOKEN': 'TEST_ONLY-stream'}) as response:
                    assert response.status_code == 200
                    lines = response.iter_lines()
                    assert next(lines) == 'retry: 3000'
                    assert len(hub._subscribers) == 1
                    hub.publish({'type': 'TEST_ONLY', 'sequence': 1})
                    while next(lines) != 'event: alert':
                        pass
                    assert '"sequence": 1' in next(lines)
                deadline = monotonic() + .75
                while hub._subscribers and monotonic() < deadline:
                    sleep(.01)
                assert not hub._subscribers, 'closed stream retained its alert subscriber'
    finally:
        app.state.research_http_snapshots.close()
