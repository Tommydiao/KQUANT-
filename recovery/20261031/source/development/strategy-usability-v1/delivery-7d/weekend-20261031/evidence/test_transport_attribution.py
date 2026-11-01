from summarize_sunday import connect_recovery_match
import pytest


@pytest.mark.parametrize('change, expected', [
    ({}, True),
    ({'ended_monotonic': 2.1}, True),
    ({'started_monotonic': 2.01}, False),
    ({'request_id': 'unrelated'}, False),
    ({'status': 401}, False),
    ({'failure_stage': 'RESPONSE_HEADERS'}, False),
    ({'path': '/unrelated'}, False),
    ({'ended_monotonic': 4.1}, False),
])
def test_connect_attribution_requires_identity_and_stage(change, expected):
    trace = dict(request_id='r1', path='/api/current', status=503,
        error_code='UPSTREAM_TIMEOUT', failure_stage='CONNECT', domain='stocks',
        started_monotonic=1.5, ended_monotonic=1.9)
    trace.update(change)
    fault = dict(fault_monotonic_start=1, replacement_ready_monotonic=2,
                 snapshot_ready_monotonic=4)
    assert connect_recovery_match(trace, 'r1', '/api/current', 'UPSTREAM_TIMEOUT', fault) is expected
