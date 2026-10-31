"""Actual gateway routes with TEST_ONLY upstream HTTP; no live SDK or stores."""
import asyncio
import json

import httpx
import pytest


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "TEST_ONLY-config"))
    monkeypatch.setenv("KQUANT_WORKSPACE_LOGIN_ENABLED", "false")
    from kquant_crypto.gateway import create_gateway_app

    def build(handler):
        return create_gateway_app(stocks_url="http://test-only-stocks.invalid",
            crypto_url="http://test-only-crypto.invalid", web_dist_dir=tmp_path,
            stocks_api_token="TEST_ONLY_token", transport=httpx.MockTransport(handler))
    return build


def read_stream(app):
    async def request():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://test-only-gateway.invalid") as client:
                return await asyncio.wait_for(client.get("/api/alerts/stream"), timeout=3)
    return asyncio.run(request())


@pytest.mark.parametrize("status", [401, 429, 503])
def test_failed_stocks_stream_never_claims_connected(gateway, status):
    seen = []

    def upstream(request):
        seen.append(request)
        return httpx.Response(status, headers={"Retry-After": "37"},
                              json={"detail": "TEST_ONLY not ready"})

    response = read_stream(gateway(upstream))
    assert "event: ready" not in response.text
    assert "event: error" in response.text
    assert f'"status": {status}' in response.text
    if status == 429:
        assert "retry: 37000" in response.text
    assert seen
    assert all(r.extensions["timeout"]["connect"] == 3 for r in seen)
    assert all(r.extensions["timeout"]["read"] == 20 for r in seen)


def test_successful_json_is_not_an_event_stream(gateway):
    response = read_stream(gateway(lambda request: httpx.Response(200, json={"status": "ok"})))
    assert "event: ready" not in response.text
    assert "STOCKS_EVENT_STREAM_CONTENT_TYPE" in response.text


def test_three_pages_share_only_pending_read_and_keep_original_times(gateway):
    async def exercise():
        started, release = asyncio.Event(), asyncio.Event()
        calls = []
        payload = {"checked_at": "2026-10-07T13:35:01+00:00",
                   "quote_received_at": "2026-10-07T13:35:00+00:00",
                   "deadline": "2026-10-07T13:40:00+00:00", "revision": 1}

        async def upstream(request):
            calls.append(request)
            started.set()
            await release.wait()
            return httpx.Response(200, json={**payload, "reads": len(calls)})

        app = gateway(upstream)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                    base_url="http://test-only-gateway.invalid") as client:
                path = "/api/options/opening-trend/current?research_strategy=opening_momentum"
                readers = [asyncio.create_task(client.get(path)) for _ in range(3)]
                await asyncio.wait_for(started.wait(), 1)
                await asyncio.sleep(.05)
                assert len(calls) == 1 and len(app.state.snapshot_requests) == 1
                readers[0].cancel()
                await asyncio.gather(readers[0], return_exceptions=True)
                assert len(calls) == 1 and not release.is_set()
                release.set()
                responses = await asyncio.gather(*readers[1:])
                assert all(r.json() == {**payload, "reads": 1} for r in responses)
                assert not app.state.snapshot_requests
                fresh = await client.get(path)
                assert fresh.json() == {**payload, "reads": 2}
                assert len(calls) == 2
                assert all(r.extensions["timeout"]["read"] == .75 for r in calls)
    asyncio.run(exercise())


def test_distinct_query_or_representation_never_shares_pending_response(gateway):
    async def exercise():
        release = asyncio.Event()
        calls = []

        async def upstream(request):
            calls.append(request)
            await release.wait()
            return httpx.Response(200, json={"query": request.url.query.decode(),
                                            "accept": request.headers["accept"]})

        app = gateway(upstream)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                    base_url="http://test-only-gateway.invalid") as client:
                tasks = [asyncio.create_task(client.get(
                    "/api/options/opening-trend/current?research_strategy=" + strategy,
                    headers={"Accept": accept}))
                    for strategy, accept in [("opening_momentum", "application/json"),
                        ("opening_trend", "application/json"), ("opening_momentum", "*/*")]]
                async def ready():
                    while len(calls) < 3:
                        await asyncio.sleep(.01)
                await asyncio.wait_for(ready(), 1)
                assert len(app.state.snapshot_requests) == 3
                release.set()
                results = await asyncio.gather(*tasks)
                assert len({json.dumps(r.json(), sort_keys=True) for r in results}) == 3
                assert not app.state.snapshot_requests
    asyncio.run(exercise())


def test_pending_snapshot_capacity_is_bounded_and_shutdown_cancels_work(gateway):
    async def exercise():
        release = asyncio.Event()
        calls = []

        async def upstream(request):
            calls.append(request)
            await release.wait()
            return httpx.Response(429, headers={"Retry-After": "37"})

        app = gateway(upstream)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                    base_url="http://test-only-gateway.invalid") as client:
                tasks = [asyncio.create_task(client.get(
                    "/api/options/opening-trend/current?symbol=" + str(n))) for n in range(16)]
                async def ready():
                    while len(calls) < 16:
                        await asyncio.sleep(.01)
                await asyncio.wait_for(ready(), 1)
                rejected = await client.get("/api/options/opening-trend/current?symbol=overflow")
                assert rejected.status_code == 503
                assert rejected.headers["Retry-After"] == "1"
                assert len(calls) == 16
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                assert len(app.state.snapshot_requests) == 16
        assert not app.state.snapshot_requests
    asyncio.run(exercise())


def test_transport_failure_marks_offline_without_fake_ready(gateway):
    def upstream(request):
        raise httpx.ReadTimeout("TEST_ONLY stalled upstream", request=request)

    response = read_stream(gateway(upstream))
    assert "event: ready" not in response.text
    assert "ReadTimeout" in response.text
    assert "event: error" in response.text


def test_real_stream_ready_and_signal_preserve_original_times(gateway):
    packet = {"type": "options_one_minute_signal", "contract_id": "TEST_ONLY_CALL",
              "bbo_received_at": "2026-10-07T13:35:01+00:00",
              "deadline_at": "2026-10-07T13:40:00+00:00", "revision": 1}

    def upstream(request):
        if "crypto" in request.url.host:
            return httpx.Response(503, json={"detail": "TEST_ONLY inactive crypto"})
        assert request.headers["X-KQUANT-API-TOKEN"] == "TEST_ONLY_token"
        return httpx.Response(200, headers={"content-type": "text/event-stream; charset=utf-8"},
                              text="data: " + json.dumps(packet) + "\n\n")

    response = read_stream(gateway(upstream))
    assert response.text.count("event: ready") == 1
    assert '"stocks_connected": true' in response.text
    wrapped = [json.loads(line[6:]) for line in response.text.splitlines()
               if line.startswith("data: ") and '"payload"' in line]
    assert json.loads(wrapped[0]["payload"]) == packet
    assert response.text.index("event: ready") < response.text.index("TEST_ONLY_CALL")
    assert "STOCKS_EVENT_STREAM_ENDED" in response.text
    assert "event: error" in response.text


def test_backend_close_is_not_silent_when_crypto_remains_available(gateway):
    def upstream(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text="")

    response = read_stream(gateway(upstream))
    assert response.text.count("event: ready") == 1
    assert "event: error" in response.text
    assert "STOCKS_EVENT_STREAM_ENDED" in response.text


def test_proxy_preserves_backoff_without_forwarding_backend_session(gateway):
    app = gateway(lambda request: httpx.Response(429, json={"detail": "TEST_ONLY rate limit"},
        headers={"Retry-After": "37", "Cache-Control": "no-store", "Set-Cookie": "TEST_ONLY_backend_session=x"}))

    async def request():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://test-only-gateway.invalid") as client:
                return await asyncio.wait_for(client.get(
                    "/api/options/opening-trend/current?research_strategy=opening_momentum"), timeout=3)
    response = asyncio.run(request())
    assert response.status_code == 429
    assert response.headers["retry-after"] == "37"
    assert response.headers["cache-control"] == "no-store"
    assert "TEST_ONLY_backend_session" not in response.headers.get("set-cookie", "")
