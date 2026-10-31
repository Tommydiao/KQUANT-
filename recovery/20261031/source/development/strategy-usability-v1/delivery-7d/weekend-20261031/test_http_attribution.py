from copy import deepcopy
import pytest
from http_attribution import classify


def fixture():
    row = dict(request_id='browser', server_request_id='forwarded', path='/api/options/opening-trend/current',
               status=503, error_code='UPSTREAM_TIMEOUT', classification='HTTP_FAILURE_REQUIRES_ATTRIBUTION')
    trace = dict(request_id='forwarded', path=row['path'], status=503,
                 error_code='UPSTREAM_TIMEOUT', domain='stocks', failure_stage='CONNECT',
                 started_monotonic=10.1, ended_monotonic=10.85)
    transport = dict(pid=2, backend_port=8193, records=[trace])
    topology = dict(controller_pid=3, backend={'pid': 1}, gateway={'pid': 2})
    fault = dict(killed_pid=1, observer_pid=3, fault_monotonic_start=10,
        replacement_ready_monotonic=12, snapshot_ready_monotonic=13,
        initial_snapshots={'states': {'current': 'FRESH', 'compact': 'FRESH'}, 'seconds': 1},
        http_contract={'target_pid': 1, 'sha256': 'TEST_ONLY', 'max_request_seconds': 3,
                       'max_recovery_seconds': 15, 'allowed': {row['path']: ['UPSTREAM_TIMEOUT']}})
    return row, transport, topology, [fault]


def test_exact_trace_process_phase_and_contract_correlation_preserves_failures():
    args = fixture()
    original = deepcopy(args)
    result = classify(*args)
    assert result['classification'] == 'DECLARED_BACKEND_CONNECT_FAULT_CORRELATED'
    assert not result['causal_network_root_proven']
    assert not result['historical_verdict_changed']
    assert args == original


@pytest.mark.parametrize('case', ['401', 'unrelated_error', 'pid', 'missing_id', 'outside', 'stale'])
def test_overlap_alone_never_exempts_failure(case):
    row, transport, topology, faults = fixture()
    if case == '401':
        row['status'] = transport['records'][0]['status'] = 401
    elif case == 'unrelated_error':
        row['error_code'] = transport['records'][0]['error_code'] = 'UNAUTHORIZED'
    elif case == 'pid':
        topology['backend']['pid'] = 999
    elif case == 'missing_id':
        row['server_request_id'] = None
    elif case == 'outside':
        transport['records'][0]['started_monotonic'] = 9.9
    elif case == 'stale':
        faults[0]['initial_snapshots']['states']['current'] = 'STALE'
    result = classify(row, transport, topology, faults)
    assert result['classification'] != 'DECLARED_BACKEND_CONNECT_FAULT_CORRELATED'
