"""TEST_ONLY TCP bridge; synthetic sources, not market or browser acceptance."""
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
import socket
import sys
from threading import Thread
from time import monotonic, sleep

import httpx
import uvicorn

from test_r58_positive_chain import prepare
from kquant.config import KquantConfig
from kquant.dashboard.app import create_app
from kquant import options_opening_momentum as model
from kquant import options_opening_trend_store as store
from kquant.options_opening_trend_pipeline import step
from kquant.security import generate_password_hash

sys.path.insert(0, str(Path(__file__).parents[1] / "crypto"))
from kquant_crypto.gateway import create_gateway_app


@contextmanager
def tcp_server(app, *, lifespan="on"):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", lifespan=lifespan,
                                         timeout_graceful_shutdown=2))
    thread = Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        limit = monotonic() + 5
        while not server.started and thread.is_alive() and monotonic() < limit:
            sleep(.01)
        assert server.started, "isolated TCP server failed to start"
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(5)
        sock.close()
        assert not thread.is_alive(), "isolated TCP server did not stop"


def test_authenticated_gateway_tcp_carries_contract_and_does_not_renew_quote(tmp_path, monkeypatch):
    args, original, services, _ = prepare(tmp_path, monkeypatch)
    clock = [args["now"]]
    path = tmp_path / "TEST_ONLY-research.sqlite3"
    store.initialize(path)
    store.persist([original], path)
    for key, value in {
        "LOCALAPPDATA": str(tmp_path / "local"),
        "KQUANT_REQUIRE_API_AUTH": "true",
        "KQUANT_API_AUTH_TOKEN": "TEST_ONLY-tcp-token",
        "KQUANT_WORKSPACE_LOGIN_ENABLED": "true",
        "KQUANT_WORKSPACE_LOGIN_EMAIL": "test-only@example.invalid",
        "KQUANT_WORKSPACE_LOGIN_PASSWORD_HASH": generate_password_hash("TEST_ONLY-password"),
        "KQUANT_WORKSPACE_SESSION_SECRET": "TEST_ONLY_SECRET" * 4,
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("KQUANT_OPTION_FOUNDATION_ROOT", raising=False)
    app = create_app(
        config=KquantConfig(db_path=tmp_path / "business.sqlite3", outputs_dir=tmp_path / "out"),
        research_store=path, research_clock=lambda: clock[0], manual_store=tmp_path / "manual.sqlite3")
    snapshots = app.state.research_http_snapshots
    snapshots.worker = lambda: {"session": original["session"], "scope_hash": "scope"}
    snapshots.observer = lambda: {"state": "TEST_ONLY", "enforced": False}
    snapshots.strategy_availability = lambda strategy: {"enabled": strategy == "opening_momentum"}
    snapshots.loader = lambda strategy, kind, worker: store.current_cards(
        path=path, session=original["session"], scope_hash="scope", now=clock[0], policy=model.load_policy())
    endpoint = "/api/options/opening-trend/current?research_strategy=opening_momentum"
    try:
        # Deliberately exclude production lifespan/SDK; exercise real HTTP/auth/proxy routes.
        with tcp_server(app, lifespan="off") as backend:
            gateway = create_gateway_app(stocks_url=backend, stocks_api_token="TEST_ONLY-tcp-token")
            with tcp_server(gateway) as address, httpx.Client(base_url=address, timeout=3) as client:
                assert client.get(endpoint).status_code == 401
                login = client.post("/api/auth/login", json={
                    "email": "test-only@example.invalid", "password": "TEST_ONLY-password"})
                assert login.status_code == 200, login.text
                job = {"evaluation": original, "progress": {}}
                for _ in range(6):
                    progress, _, revision = step(job, services, clock=lambda: clock[0])
                    job["progress"] = progress
                assert revision["state"] == "QUALIFIED"
                store.append_revision(original["evaluation_id"], revision, path)
                limit = monotonic() + 3
                payload = {}
                while monotonic() < limit:
                    snapshots.tick()
                    result = client.get(endpoint)
                    if result.status_code == 200:
                        payload = result.json()
                        if payload.get("candidates"):
                            break
                    sleep(.01)
                assert len(payload.get("candidates", [])) == 1, payload
                card = payload["candidates"][0]
                assert card["evaluation_id"] == original["evaluation_id"]
                assert card["contract_id"] == "TEST261006C105000.US"
                assert card["deadline_at"] == original["deadline_at"]
                clock[0] += timedelta(seconds=3)
                expired = client.get(endpoint)
                assert expired.status_code == 200
                assert expired.json()["candidates"] == []
                assert client.post("/api/auth/logout").status_code == 200
                assert client.get(endpoint).status_code == 401
    finally:
        snapshots.close()
