import asyncio
import importlib.util
from pathlib import Path
import sys
import httpx
import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "workspace" / "crypto"))
spec = importlib.util.spec_from_file_location("kquant_crypto.gateway_candidate", HERE / "gateway_candidate.py")
gateway = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gateway
spec.loader.exec_module(gateway)


@pytest.mark.parametrize("failure,code", [
    (httpx.ConnectError, "UPSTREAM_CONNECTION_FAILED"),
    (httpx.ReadTimeout, "UPSTREAM_TIMEOUT"),
])
def test_error_provenance_survives_unread_body(monkeypatch, tmp_path, failure, code):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("KQUANT_WORKSPACE_LOGIN_ENABLED", "false")
    async def upstream(request):
        raise failure("TEST_ONLY_PRIVATE_TEXT_NOT_FOR_HEADERS")
    app = gateway.create_gateway_app(stocks_url="http://isolated.invalid",
                                     transport=httpx.MockTransport(upstream))
    async def run():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),
                                         base_url="http://test.invalid") as client:
                result = await client.get("/api/options/one-minute/status")
                assert result.status_code == 503
                assert result.headers["x-kquant-error-code"] == code
                assert result.headers["x-kquant-error-origin"] == "GATEWAY_UPSTREAM"
                assert len(result.headers["x-request-id"]) == 32
                assert "PRIVATE" not in str(result.headers)
                assert result.json()["error_code"] == code
    asyncio.run(run())


def test_upstream_rate_limit_keeps_identity_and_budget(monkeypatch, tmp_path):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setenv('KQUANT_WORKSPACE_LOGIN_ENABLED', 'false')
    seen = []
    async def upstream(request):
        seen.append(request.headers['x-request-id'])
        return httpx.Response(429, json={'detail': 'rate limit'}, headers={'Retry-After': '1'})
    app = gateway.create_gateway_app(stocks_url='http://isolated.invalid',
                                    transport=httpx.MockTransport(upstream))
    async def run():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test.invalid') as client:
                result = await client.get('/api/options/one-minute/status')
                assert result.status_code == 429
                assert result.headers['x-request-id'] == seen[0]
                assert result.headers['retry-after'] == '1'
                assert result.headers['x-kquant-error-origin'] == 'UPSTREAM_HTTP'
                assert app.state.transport_failure_count == 0
    asyncio.run(run())
