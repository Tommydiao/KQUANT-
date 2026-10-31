"""Real local TCP test. No credentials, external request, SDK or service restart."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import sys
from threading import Thread

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent/'opening-first-hour/assembly'))
from live_fact_topology import local_http_client


@contextmanager
def server(status):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(self.path)
            self.send_response(status)
            self.send_header('Content-Length', '0')
            self.end_headers()

        def log_message(self, *args):
            pass

    owner = HTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=owner.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{owner.server_port}', requests
    finally:
        owner.shutdown()
        owner.server_close()
        thread.join(2)
        assert not thread.is_alive()


def test_local_probe_never_sends_test_requests_to_inherited_proxy(monkeypatch):
    with server(502) as (proxy, proxy_requests), server(200) as (base, local_requests):
        monkeypatch.setenv('HTTP_PROXY', proxy)
        monkeypatch.setenv('HTTPS_PROXY', proxy)
        monkeypatch.setenv('NO_PROXY', '')
        with httpx.Client(timeout=3) as inherited:
            assert inherited.get(base+'/api/health/live').status_code == 502
        assert len(proxy_requests) == 1
        with local_http_client(base, timeout=3) as direct:
            assert direct.get('/api/health/live').status_code == 200
        assert len(proxy_requests) == 1
        assert local_requests == ['/api/health/live']


@pytest.mark.parametrize('base', ['https://127.0.0.1:8194', 'http://localhost:8194',
                                'http://example.com', 'http://user:password@127.0.0.1'])
def test_isolated_client_rejects_non_literal_loopback(base):
    with pytest.raises(ValueError, match='ISOLATED_LOOPBACK_HTTP_REQUIRED'):
        local_http_client(base, timeout=3)
