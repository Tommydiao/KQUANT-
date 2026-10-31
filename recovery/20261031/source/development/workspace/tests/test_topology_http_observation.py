from datetime import datetime
import importlib.util
from pathlib import Path

import httpx
import pytest


def observer():
    path = Path(__file__).parents[1] / "scripts/check_r58_p10_topology.py"
    spec = importlib.util.spec_from_file_location("isolated_http_observation", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.observe_http


@pytest.mark.parametrize("failure", [None, httpx.ReadError, httpx.RemoteProtocolError])
def test_every_attempt_has_identity_and_time_without_retry_or_secrets(failure):
    seen = []
    def transport(request):
        seen.append(request)
        if failure:
            raise failure("SECRET_MUST_NOT_BE_LOGGED", request=request)
        return httpx.Response(200, json={"ok": True})
    with httpx.Client(transport=httpx.MockTransport(transport), base_url="http://test.invalid") as client:
        row = observer()(client, "/api/health/live", 2, 4)
    assert len(seen) == 1
    assert seen[0].headers["X-Request-ID"] == row["request_id"]
    assert row["sequence"] == 4 and row["page"] == 2
    assert datetime.fromisoformat(row["started_at"]).tzinfo is not None
    assert datetime.fromisoformat(row["observed_at"]).tzinfo is not None
    assert row["seconds"] >= 0
    assert "SECRET" not in str(row)
    assert row.get("error") == (failure.__name__ if failure else None)
    assert row["status"] == (None if failure else 200)


@pytest.mark.parametrize('detail,expected', [
    ('CURRENT_CARDS_UNAVAILABLE', 'CURRENT_CARDS_UNAVAILABLE'),
    ('SECRET_MUST_NOT_BE_LOGGED', 'UNCLASSIFIED_RESPONSE'),
    ({'secret': 'SECRET_MUST_NOT_BE_LOGGED'}, 'UNCLASSIFIED_RESPONSE'),
])
def test_failure_body_only_exposes_exact_allowlisted_code(detail, expected):
    with httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(503, json={'detail': detail})),
        base_url='http://test.invalid') as client:
        row = observer()(client, '/api/options/opening-trend/current', 0, 1)
    assert row['response_error_code'] == expected
    assert 'SECRET' not in str(row)
