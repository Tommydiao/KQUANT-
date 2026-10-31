"""Isolated transport tests: real Gateway routes, no credentials or SDK."""
import asyncio
import importlib.util
from pathlib import Path
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx
import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('TEST_ONLY_gateway_pool',
    HERE/'transport-followup/patches/crypto/kquant_crypto/gateway.py')
gateway = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gateway
spec.loader.exec_module(gateway)
PATH = '/api/options/opening-trend/current?research_strategy=opening_momentum'


@pytest.fixture
def configured(monkeypatch, tmp_path):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setenv('KQUANT_WORKSPACE_LOGIN_ENABLED', 'false')
    return tmp_path


def app_for(tmp_path, handler):
    return gateway.create_gateway_app(stocks_url='http://test.invalid',
        crypto_url='http://test.invalid', web_dist_dir=tmp_path,
        stocks_api_token='TEST_ONLY', transport=httpx.MockTransport(handler))


def test_connection_owner_and_no_cookie_or_response_cache(configured):
    async def run():
        calls = []
        async def handler(request):
            calls.append(dict(request.headers))
            return httpx.Response(200, json={'revision': len(calls)},
                headers={'Set-Cookie': 'backend_secret=TEST_ONLY; Path=/'})
        app = app_for(configured, handler)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://gateway') as client:
                first = await client.get(PATH)
                owner = app.state.snapshot_client
                second = await client.get(PATH)
                assert first.json()['revision'] == 1
                assert second.json()['revision'] == 2
                assert app.state.snapshot_client is owner
                assert all('cookie' not in headers for headers in calls)
                assert len(owner.cookies) == 0
                assert calls[0]['x-kquant-api-token'] == 'TEST_ONLY'
        assert owner.is_closed and app.state.snapshot_client is None
    asyncio.run(run())


def test_three_readers_share_only_inflight_then_fetch_new_revision(configured):
    async def run():
        calls = 0
        async def handler(request):
            nonlocal calls
            calls += 1
            await asyncio.sleep(.03)
            return httpx.Response(200, json={'revision': calls})
        app = app_for(configured, handler)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://gateway') as client:
                responses = await asyncio.gather(*(client.get(PATH) for _ in range(3)))
                assert [response.status_code for response in responses] == [200]*3
                assert calls == 1
                await client.get(PATH)
                assert calls == 2
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['connect', 'receive', 'slow'])
def test_fault_fast_failure_no_retry_and_next_request_recovers(configured, failure):
    async def run():
        calls = 0
        async def handler(request):
            nonlocal calls
            calls += 1
            if calls == 1:
                if failure == 'slow':
                    await asyncio.sleep(5)
                elif failure == 'connect':
                    raise httpx.ConnectError('TEST_ONLY', request=request)
                else:
                    raise httpx.ReadTimeout('TEST_ONLY', request=request)
            return httpx.Response(200, json={'revision': calls})
        app = app_for(configured, handler)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://gateway') as client:
                start = asyncio.get_running_loop().time()
                failed = await client.get(PATH)
                assert failed.status_code == 503
                assert asyncio.get_running_loop().time()-start < 1.2
                assert calls == 1
                recovered = await client.get(PATH)
                assert recovered.status_code == 200
                assert calls == 2
    asyncio.run(run())


def test_shutdown_cancels_pending_reads_and_closes_owner(configured):
    async def run():
        entered = asyncio.Event()
        async def handler(request):
            entered.set()
            await asyncio.sleep(5)
            return httpx.Response(200, json={})
        app = app_for(configured, handler)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://gateway') as client:
                request = asyncio.create_task(client.get(PATH))
                await entered.wait()
                owner = app.state.snapshot_client
        result = await asyncio.gather(request, return_exceptions=True)
        assert owner.is_closed
        assert app.state.snapshot_requests == {}
        assert isinstance(result[0], BaseException)
    asyncio.run(run())


def test_actual_tcp_reuses_connection_and_reopens_after_peer_close(configured):
    peers = []
    cookies = []
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        def log_message(self, *args):
            pass
        def do_GET(self):
            peers.append(self.client_address)
            cookies.append(self.headers.get('cookie'))
            body = b'{"test_only":true}'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Set-Cookie', 'secret=TEST_ONLY; Path=/')
            if len(peers) == 3:
                self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    async def run():
        app = gateway.create_gateway_app(stocks_url=f'http://127.0.0.1:{server.server_port}',
            crypto_url='http://test.invalid', web_dist_dir=configured)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://gateway') as client:
                for _ in range(6):
                    assert (await client.get(PATH)).status_code == 200
    try:
        asyncio.run(run())
        assert peers[0] == peers[1] == peers[2]
        assert peers[3] == peers[4] == peers[5]
        assert peers[0] != peers[3]
        assert cookies == [None]*6
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
