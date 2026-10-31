import asyncio
from pathlib import Path
import sys
from time import monotonic

import httpx

sys.path.insert(0, str(Path(__file__).parents[1] / 'crypto'))
from kquant_crypto.gateway import create_gateway_app


def test_slow_manual_read_is_bounded_single_flight_and_never_returns_empty_success(monkeypatch, tmp_path):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    monkeypatch.setenv('KQUANT_WORKSPACE_LOGIN_ENABLED', 'false')
    calls = []
    async def upstream(request):
        calls.append(request.url.path)
        await asyncio.sleep(5)
        return httpx.Response(200, json={'positions': []})
    app = create_gateway_app(stocks_url='http://isolated.invalid', transport=httpx.MockTransport(upstream))
    async def exercise():
        started = monotonic()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test.invalid') as client:
                results = await asyncio.gather(*[client.get('/api/options/one-minute/manual') for _ in range(3)])
        assert monotonic() - started < 2
        assert all(r.status_code == 503 and r.headers['Retry-After'] == '1' for r in results)
    asyncio.run(exercise())
    assert calls == ['/api/options/one-minute/manual']
