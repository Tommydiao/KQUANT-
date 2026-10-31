import asyncio
from pathlib import Path
import sys

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "crypto"))
from kquant_crypto.gateway import create_gateway_app, _filtered_headers


@pytest.mark.parametrize("marker,expected", [
    ("legacy-not-mounted", "legacy-not-mounted"),
    ("", None),
    ("unknown", None),
])
def test_proxy_preserves_only_explicit_isolation_provenance(monkeypatch, tmp_path, marker, expected):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("KQUANT_WORKSPACE_LOGIN_ENABLED", "false")

    async def upstream(request):
        return httpx.Response(503, json={"detail": "unavailable"}, headers={
            "x-kquant-test-isolation": marker,
            "x-request-id": "TEST_ONLY-backend-42",
            "set-cookie": "private=value",
            "authorization": "private",
        })

    app = create_gateway_app(stocks_url="http://isolated.invalid", transport=httpx.MockTransport(upstream))

    async def exercise():
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test.invalid") as client:
                result = await client.get("/api/options/status")
        assert result.status_code == 503
        assert result.headers.get("x-kquant-test-isolation") == expected
        assert result.headers["x-request-id"] == "TEST_ONLY-backend-42"
        assert "private" not in str(result.headers)

    asyncio.run(exercise())


@pytest.mark.parametrize("request_id", ["x" * 129, "private token", "nonascii-\u00e9"])
def test_invalid_request_identifiers_are_not_forwarded(request_id):
    response = httpx.Response(503)
    response.headers = httpx.Headers({"x-request-id": request_id}, encoding="utf-8")
    assert "x-request-id" not in _filtered_headers(response)


def test_marker_does_not_hide_other_status_codes():
    response = httpx.Response(500, headers={"x-kquant-test-isolation": "legacy-not-mounted"})
    assert "x-kquant-test-isolation" not in _filtered_headers(response)
