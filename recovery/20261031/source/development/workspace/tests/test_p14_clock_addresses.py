"""Bounded same-host transport; external UDP is never used by these tests."""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import socket
import struct
from threading import Event, Thread
import time

import pytest

from kquant import options_clock_measurement as clock


HOST = clock.METHOD['servers'][0]
CODE = Path(clock.__file__).resolve().parent.parent
EXPECTED_METHOD = {
    'version': 'NTP_INTERVAL_BOUND_V1',
    'servers': ['time.cloudflare.com', 'time.windows.com'],
    'minimum_sources': 2, 'max_age_seconds': 900, 'max_uncertainty_ms': 1000,
    'maximum_wall_jump_ms': 50,
    'trust_assumption': 'LISTED_SERVERS_ACCURATE_AND_NO_UDP_SPOOFING',
    'system_clock_modified': False,
}


def address(ip, *, family=socket.AF_INET, port=123):
    target = (ip, port, 0, 0) if family == socket.AF_INET6 else (ip, port)
    return family, socket.SOCK_DGRAM, socket.IPPROTO_UDP, '', target


def packet(nonce, *, shift=0):
    reply = bytearray(48)
    reply[0], reply[1], reply[3] = 0x24, 2, 236
    reply[24:32] = nonce
    reply[32:40] = clock.stamp(time.time() + shift)
    reply[40:48] = clock.stamp(time.time() + shift)
    return bytes(reply)


def transport(monkeypatch, candidates, outcomes):
    requests, sockets = [], []

    def resolve(host, port, **kwargs):
        requests.append((host, port, kwargs))
        return candidates

    class Peer:
        def __init__(self, family, kind):
            self.family, self.kind = family, kind
            self.timeouts = []
            sockets.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.closed = True

        def settimeout(self, value):
            assert 0 < value <= clock.UDP_ATTEMPT_TIMEOUT_SECONDS
            self.timeouts.append(value)

        def connect(self, target):
            self.target = target
            outcome = outcomes[target[0]]
            if isinstance(outcome, Exception):
                raise outcome

        def send(self, request):
            self.nonce = bytes(request[40:48])
            return len(request)

        def recv(self, size):
            outcome = outcomes[self.target[0]]
            if callable(outcome):
                return outcome(self)
            if outcome == 'invalid':
                return b'bad'
            return packet(self.nonce, shift=outcome)

    monkeypatch.setattr(clock.socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(clock.socket, 'socket', Peer)
    return requests, sockets


def hashed(row):
    assert row['observation_hash'] == clock.common.digest(
        {key: value for key, value in row.items() if key != 'observation_hash'})


def sample(host, *, shift=0, radius_delay=.2):
    now = datetime.now(UTC)
    t1, t4 = now.timestamp() - radius_delay, now.timestamp()
    t2 = clock.decode(clock.stamp(t1 + .08 + shift))
    t3 = clock.decode(clock.stamp(t1 + .081 + shift))
    raw = bytearray(48)
    raw[0], raw[1], raw[3] = 0x24, 2, 246
    raw[24:32], raw[32:40], raw[40:48] = clock.stamp(t1), clock.stamp(t2), clock.stamp(t3)
    row = dict(server=host, address='192.0.2.1', t1=t1, t2=t2, t3=t3, t4=t4,
               monotonic_elapsed_seconds=t4 - t1, offset_seconds=((t2-t1)+(t3-t4))/2,
               uncertainty_radius_seconds=((t4-t1)-(t3-t2))/2 + 2**-10 + .002,
               packet_hex=raw.hex(), checked_at=now.isoformat(), udp_authenticated=False)
    row['observation_hash'] = clock.common.digest(row)
    return row


def acceptance(tmp_path):
    now = datetime.now(UTC)
    receipt = dict(status='ACCEPTED', accepted_by='OWNER', method=EXPECTED_METHOD,
                   method_hash=clock.common.digest(EXPECTED_METHOD), accepted_at=now.isoformat(),
                   valid_until=(now + timedelta(hours=1)).isoformat(), test_only=True)
    raw = json.dumps(receipt).encode('utf-8')
    target = tmp_path / 'TEST_ONLY-clock-acceptance.json'
    target.write_bytes(raw)
    return dict(acceptance_path=target.name, acceptance_sha256=sha256(raw).hexdigest())


def test_accepted_method_constants_unchanged():
    assert clock.METHOD == EXPECTED_METHOD
    assert clock.PER_HOST_TIMEOUT_SECONDS * len(clock.METHOD['servers']) <= clock.CHILD_TOTAL_TIMEOUT_SECONDS < 6


@pytest.mark.parametrize('family,first,second', [
    (socket.AF_INET, '192.0.2.1', '192.0.2.2'),
    (socket.AF_INET6, '2001:db8::1', '2001:db8::2'),
])
def test_second_ip_same_hostname_after_network_failure(monkeypatch, family, first, second):
    requests, peers = transport(monkeypatch, [address(first, family=family), address(second, family=family)],
                                {first: ConnectionRefusedError(10061, 'TEST_ONLY'), second: 0})
    row = clock.query(HOST)
    assert [request[:2] for request in requests] == [(HOST, 123)]
    assert requests[0][2] == dict(family=socket.AF_UNSPEC, type=socket.SOCK_DGRAM, proto=socket.IPPROTO_UDP)
    assert row['server'] == HOST and row['address'] == second
    attempts = row['transport_diagnostic']['attempts']
    assert [item['phase'] for item in attempts] == ['NETWORK', 'COMPLETE']
    assert attempts[0]['error_code'] == 10061
    assert all(peer.closed for peer in peers)
    assert all(peer.family == family for peer in peers)
    hashed(row)


def test_ipv6_packet_failure_falls_back_to_ipv4_with_same_nonce_checks(monkeypatch):
    _, peers = transport(monkeypatch, [address('2001:db8::1', family=socket.AF_INET6), address('192.0.2.1')],
                         {'2001:db8::1': 'invalid', '192.0.2.1': 0})
    row = clock.query(HOST)
    attempts = row['transport_diagnostic']['attempts']
    assert [(item['family'], item['phase']) for item in attempts] == [('AF_INET6', 'PACKET'), ('AF_INET', 'COMPLETE')]
    assert [peer.family for peer in peers] == [socket.AF_INET6, socket.AF_INET]
    assert attempts[0]['error_type'] == 'ValueError'
    hashed(row)


def test_candidates_are_distinct_bounded_and_follow_resolver_order(monkeypatch):
    ips = ['192.0.2.' + str(index) for index in range(1, 10)]
    candidates = [address(ips[0])] * 3 + [address(ip) for ip in ips]
    _, peers = transport(monkeypatch, candidates, {ip: OSError(10051, 'TEST_ONLY') for ip in ips})
    with pytest.raises(OSError) as caught:
        clock.query(HOST)
    diagnostic = caught.value.transport_diagnostic
    assert [item['address'] for item in diagnostic['dns']['candidates']] == ips[:clock.MAX_DNS_CANDIDATES]
    assert [peer.target[0] for peer in peers] == ips[:clock.MAX_DNS_CANDIDATES]
    assert len(diagnostic['attempts']) == clock.MAX_DNS_CANDIDATES


def test_wrong_port_family_and_non_udp_results_never_become_attempts(monkeypatch):
    invalid = [address('192.0.2.1', port=124), address('2001:db8::1'),
               (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('192.0.2.2', 123)),
               (socket.AF_INET6, socket.SOCK_DGRAM, socket.IPPROTO_UDP, '', ('2001:db8::1', 123))]
    _, peers = transport(monkeypatch, invalid, {})
    with pytest.raises(OSError) as caught:
        clock.query(HOST)
    assert caught.value.transport_diagnostic['dns']['phase'] == 'NO_USABLE_ADDRESS'
    assert not peers


def test_first_valid_unfavorable_offset_stops_all_further_ip_selection(monkeypatch):
    _, peers = transport(monkeypatch, [address('192.0.2.1'), address('192.0.2.2')],
                         {'192.0.2.1': 5, '192.0.2.2': 0})
    row = clock.query(HOST)
    assert row['offset_seconds'] > 4.9
    assert row['transport_diagnostic']['selection'] == 'FIRST_VALID_PACKET_IN_DNS_ORDER'
    assert len(peers) == len(row['transport_diagnostic']['attempts']) == 1
    hashed(row)


def test_dns_stall_is_bounded_without_udp(monkeypatch):
    entered, release = Event(), Event()

    def resolve(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return [address('192.0.2.1')]

    monkeypatch.setattr(clock.socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(clock, 'DNS_TIMEOUT_SECONDS', .05)
    began = time.monotonic()
    try:
        with pytest.raises(TimeoutError) as caught:
            clock.query(HOST)
        assert entered.is_set()
        assert time.monotonic() - began < .5
        diagnostic = caught.value.transport_diagnostic
        assert diagnostic['dns']['phase'] == 'DNS_TIMEOUT' and not diagnostic['attempts']
    finally:
        release.set()


def test_dns_error_keeps_specific_error_code(monkeypatch):
    def resolve(*args, **kwargs):
        raise socket.gaierror(11001, 'TEST_ONLY')

    monkeypatch.setattr(clock.socket, 'getaddrinfo', resolve)
    with pytest.raises(socket.gaierror) as caught:
        clock.query(HOST)
    dns = caught.value.transport_diagnostic['dns']
    assert dns['phase'] == 'DNS_ERROR' and dns['error_code'] == 11001
    assert caught.value.transport_diagnostic['attempts'] == []


@pytest.mark.parametrize('remaining', [None, .2])
def test_udp_attempts_share_per_host_and_child_deadline(monkeypatch, remaining):
    elapsed = [100.0]
    monkeypatch.setattr(clock.time, 'monotonic', lambda: elapsed[0])

    def timeout(peer):
        elapsed[0] += peer.timeouts[-1]
        raise TimeoutError('TEST_ONLY UDP timeout')

    ips = ['192.0.2.' + str(index) for index in range(1, 5)]
    _, peers = transport(monkeypatch, [address(ip) for ip in ips], {ip: timeout for ip in ips})
    deadline = None if remaining is None else elapsed[0] + remaining
    with pytest.raises(TimeoutError) as caught:
        clock.query(HOST, deadline=deadline)
    limit = clock.PER_HOST_TIMEOUT_SECONDS if remaining is None else remaining
    assert elapsed[0] - 100 <= limit + 1e-9
    assert len(peers) == clock.MAX_DNS_CANDIDATES
    assert all(max(peer.timeouts) <= min(clock.UDP_ATTEMPT_TIMEOUT_SECONDS, limit) for peer in peers)
    assert caught.value.transport_diagnostic['elapsed_seconds'] <= limit + 1e-9


def test_expired_child_deadline_does_not_even_resolve(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('expired round must not resolve or open UDP')

    monkeypatch.setattr(clock.socket, 'getaddrinfo', forbidden)
    monkeypatch.setattr(clock.socket, 'socket', forbidden)
    with pytest.raises(TimeoutError) as caught:
        clock.query(HOST, deadline=time.monotonic() - 1)
    assert caught.value.transport_diagnostic['phase'] == 'DEADLINE'
    assert caught.value.transport_diagnostic['attempts'] == []


@pytest.mark.parametrize('endpoint', [('192.0.2.1', 123), ('127.0.0.1', 123), ('127.0.0.1', True)])
def test_direct_query_cannot_bypass_loopback_test_only_endpoint_guard(endpoint):
    with pytest.raises(ValueError, match='TEST_ONLY_UDP_ENDPOINTS_INVALID'):
        clock.query(HOST, endpoint=endpoint)


def test_new_hostname_cannot_be_queried():
    with pytest.raises(ValueError, match='NTP_SERVER_NOT_LISTED'):
        clock.query('TEST_ONLY_UNLISTED')


def test_duplicate_host_observations_are_not_extra_or_selectable_sources(tmp_path):
    proof = acceptance(tmp_path)
    rows = [sample(host) for host in clock.METHOD['servers']]
    assert clock.evaluate(rows, proof=proof, root=tmp_path, now=datetime.now(UTC))['precision_verified']
    duplicate = deepcopy(rows[0])
    duplicate['address'] = '192.0.2.2'
    duplicate['observation_hash'] = clock.common.digest({key: value for key, value in duplicate.items()
                                                       if key != 'observation_hash'})
    for duplicates in ([rows[0], duplicate], [rows[0], duplicate, rows[1]]):
        value = clock.evaluate(duplicates, proof=proof, root=tmp_path, now=datetime.now(UTC))
        assert not value['precision_verified'] and value['uncertainty_ms'] is None


def test_test_only_transport_cannot_verify_even_with_accepted_method(tmp_path):
    rows = [sample(host) for host in clock.METHOD['servers']]
    for row in rows:
        row['test_only_transport'] = True
        row['observation_hash'] = clock.common.digest({key: value for key, value in row.items()
                                                      if key != 'observation_hash'})
    value = clock.evaluate(rows, proof=acceptance(tmp_path), root=tmp_path, now=datetime.now(UTC))
    assert value['state'] == 'MEASUREMENT_UNAVAILABLE' and not value['precision_verified']


def loopback_peer(*, invalid=False):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', 0))
    sock.settimeout(5)
    port = sock.getsockname()[1]

    def answer():
        try:
            request, target = sock.recvfrom(512)
            sock.sendto(b'bad' if invalid else packet(request[40:48]), target)
        finally:
            sock.close()

    thread = Thread(target=answer)
    thread.start()
    return port, thread


@pytest.mark.parametrize('invalid', [False, True])
def test_real_monitor_child_keeps_returncode_bounded_stderr_and_test_only(tmp_path, monkeypatch, invalid):
    monkeypatch.delenv('PYTHONPATH', raising=False)
    peers = [loopback_peer(invalid=invalid), loopback_peer(invalid=invalid)]
    endpoints = {host: ['127.0.0.1', peer[0]] for host, peer in zip(clock.METHOD['servers'], peers)}
    proof_file = tmp_path / 'TEST_ONLY-method.json'
    proof_file.write_text(json.dumps(acceptance(tmp_path)), encoding='utf-8')
    monitor = clock.ClockAttachmentMonitor(code_root=CODE, data_root=tmp_path,
                method_config_path=proof_file, acceptance_root=tmp_path, udp_test_endpoints=endpoints)
    stored = []
    monkeypatch.setattr(monitor, '_store', lambda value: stored.append(deepcopy(value)))
    monitor.next_system_check = float('inf')
    began = time.monotonic()
    try:
        value = monitor.tick(datetime.now(UTC))
        while monitor.child is not None and time.monotonic() - began < 8:
            time.sleep(.02)
            value = monitor.tick(datetime.now(UTC))
        assert monitor.child is None
        diagnostic = value['child_diagnostic']
        assert diagnostic['returncode'] == 0 and diagnostic['phase'] == 'COMPLETE'
        assert 0 < len(diagnostic['stderr']) <= 8192 and not diagnostic['stderr_truncated']
        assert len(value['samples']) == len(clock.METHOD['servers']) == 2
        assert [row['server'] for row in value['samples']] == clock.METHOD['servers']
        assert value['test_only'] and not value['precision_verified'] and value['uncertainty_ms'] is None
        assert value['method_accepted'] and not value['system_clock_modified']
        assert stored
        for row in value['samples']:
            assert row['test_only_transport']
            attempts = row['transport_diagnostic']['attempts']
            assert len(attempts) == 1
            assert attempts[0]['address'] == '127.0.0.1'
            assert attempts[0]['phase'] == ('PACKET' if invalid else 'COMPLETE')
            if not invalid:
                hashed(row)
    finally:
        monitor.close()
        for _, thread in peers:
            thread.join(timeout=6)
            assert not thread.is_alive()
