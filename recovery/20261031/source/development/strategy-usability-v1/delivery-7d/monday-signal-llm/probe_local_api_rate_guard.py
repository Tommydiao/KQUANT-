"""Explicit ASGI-only evidence of the existing local API budget, no real data."""
import asyncio
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import sys
from unittest.mock import patch

import httpx
from fastapi import FastAPI

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[4]/'source/development/workspace'
sys.path.insert(0, str(BASE))
from kquant.security import ApiSecurityMiddleware, LocalSessionAuth, SecuritySettings


async def main():
    token = secrets.token_hex(32)
    with patch.dict(os.environ, {'KQUANT_REQUIRE_API_AUTH':'1', 'KQUANT_API_AUTH_TOKEN':token,
            'KQUANT_API_RATE_LIMIT_PER_MINUTE':'240', 'KQUANT_LOGIN_ENABLED':'0'}):
        settings = SecuritySettings.from_environment()
        app = FastAPI()
        app.add_middleware(ApiSecurityMiddleware, settings=settings,
            session_auth=LocalSessionAuth(settings))
        @app.get('/api/options/opening-trend/current')
        async def current():
            return {'test_only':True, 'actual_market':False}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test-only',
                headers={'X-KQUANT-API-TOKEN':token}) as client:
            statuses = []
            for _ in range(241):
                response = await client.get('/api/options/opening-trend/current')
                statuses.append(response.status_code)
        assert statuses[:240] == [200]*240 and statuses[240] == 429
        assert response.json() == {'detail':'API rate limit reached. Retry later.'}
        assert 1 <= int(response.headers['retry-after']) <= 60
        result = dict(test_only=True, observed_at=datetime.now(UTC).isoformat(),
            transport='IN_PROCESS_ASGI_NOT_REAL_TCP_OR_MARKET', actual_security_middleware=True,
            configured_local_budget=settings.rate_limit_per_minute, attempts=len(statuses),
            accepted=statuses.count(200), rejected=statuses.count(429),
            rate_response_bytes=len(response.content), rate_response_sha256=sha256(response.content).hexdigest(),
            retry_after_seconds=int(response.headers['retry-after']), authentication_still_required=True,
            production_settings_changed=False, production_writes=0, sdk_requests=0, model_requests=0,
            historical_wire_body_proven=False,
            inference='Matches the observed49byte429 signature; exact two historical responses remain unproven until per-request guard evidence is captured.')
        path = HERE/'evidence/local-api-rate-guard-20261020.json'
        with path.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
        print(json.dumps({'path':str(path), **result}))


if __name__ == '__main__':
    asyncio.run(main())
