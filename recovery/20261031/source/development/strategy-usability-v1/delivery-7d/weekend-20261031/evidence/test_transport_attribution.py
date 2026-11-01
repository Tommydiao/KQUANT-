from summarize_sunday import connect_recovery_match, cold_receive_match
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


@pytest.mark.parametrize('change, expected', [
    ({}, True), ({'request_id': 'other'}, False), ({'pid': 99}, False),
    ({'error': 'SQLITE_BUSY'}, False), ({'caches': []}, False),
    ({'observed_at': '2026-11-01T13:02:25.500+00:00'}, False),
])
def test_cold_receive_requires_exact_backend_proof(change, expected):
    row = dict(status=503, response_error_code='UPSTREAM_TIMEOUT',
        response_failure_stage='RECEIVE', response_error_origin='GATEWAY_UPSTREAM',
        server_request_id='r1', path='/api/status?compact=true',
        observed_at='2026-11-01T13:02:25.330+00:00')
    trace = dict(status=503, error_code='UPSTREAM_TIMEOUT', failure_stage='RECEIVE',
        domain='stocks', request_id='r1', path='/api/status',
        started_monotonic=1.5, ended_monotonic=2.2)
    proof = dict(request_id='r1', path='/api/status', pid=2, stage='HTTP_503', error=None,
        observed_at='2026-11-01T13:02:25.356+00:00', caches=[dict(kind='compact',
            strategy='opening_momentum', has_value=False, generation=0, pending_key=['date'], error=None)])
    proof.update(change)
    fault = dict(replacement_pid=2, fault_monotonic_start=1,
                 replacement_ready_monotonic=2, snapshot_ready_monotonic=4)
    assert cold_receive_match(row, trace, proof, fault) is expected
    row['status'] = 401
    assert not cold_receive_match(row, trace, proof, fault)
