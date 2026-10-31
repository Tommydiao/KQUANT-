import ssl
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from kquant_crypto.gateway import create_gateway_app


def test_proxy_does_not_reload_ca_files_and_keeps_verification(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("KQUANT_WORKSPACE_LOGIN_ENABLED", "false")
    contexts = []
    original = ssl.create_default_context

    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        contexts.append(result)
        return result

    with patch("ssl.create_default_context", capture):
        app = create_gateway_app(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"status": "online"})))
        assert len(contexts) == 1
        with TestClient(app) as client:
            for _ in range(5):
                assert client.get("/api/stocks/health/live").status_code == 200
        assert len(contexts) == 1
    assert contexts[0].verify_mode == ssl.CERT_REQUIRED
    assert contexts[0].check_hostname
