"""Read-only NTP observations. No Windows service or system-clock changes."""
from copy import deepcopy
from collections import Counter
from datetime import UTC, datetime
import ipaddress
import json
import argparse
import re
from pathlib import Path
from queue import Empty, Queue
import socket
import struct
import subprocess
import sys
from threading import RLock, Thread
import time

from . import options_one_minute as common

EPOCH = 2208988800
METHOD = {"version": "NTP_INTERVAL_BOUND_V1", "servers": ["time.cloudflare.com", "time.windows.com"],
          "minimum_sources": 2, "max_age_seconds": 900, "max_uncertainty_ms": 1000,
          "maximum_wall_jump_ms": 50, "trust_assumption": "LISTED_SERVERS_ACCURATE_AND_NO_UDP_SPOOFING",
          "system_clock_modified": False}
MAX_DNS_CANDIDATES = 4
DNS_TIMEOUT_SECONDS = .75
PER_HOST_TIMEOUT_SECONDS = 2.0
UDP_ATTEMPT_TIMEOUT_SECONDS = 1.0
CHILD_TOTAL_TIMEOUT_SECONDS = 4.5
_lock = RLock()
_attachment = {"state": "NOT_MEASURED", "precision_verified": False}
_published_time = None


def stamp(value):
    seconds = value + EPOCH
    return struct.pack("!II", int(seconds), int((seconds % 1) * 2**32))


def decode(raw):
    seconds, fraction = struct.unpack("!II", raw)
    return seconds - EPOCH + fraction / 2**32


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('NTP_DEADLINE_EXCEEDED')
    return remaining


def _resolve_candidates(endpoint, deadline, diagnostic):
    result = Queue(maxsize=1)

    def resolve():
        try:
            result.put(socket.getaddrinfo(*endpoint, family=socket.AF_UNSPEC,
                                         type=socket.SOCK_DGRAM, proto=socket.IPPROTO_UDP))
        except (OSError, ValueError) as exc:
            result.put(exc)

    started = time.monotonic()
    timeout = min(DNS_TIMEOUT_SECONDS, _remaining(deadline))
    # A stalled platform resolver must not hold the measurement child open.
    Thread(target=resolve, daemon=True).start()
    try:
        rows = result.get(timeout=timeout)
    except Empty:
        diagnostic['phase'] = 'DNS_TIMEOUT'
        raise TimeoutError('NTP_DNS_TIMEOUT') from None
    finally:
        diagnostic['elapsed_seconds'] = max(0, time.monotonic() - started)
    _remaining(deadline)
    if isinstance(rows, Exception):
        diagnostic.update(phase='DNS_ERROR', error_type=type(rows).__name__,
                          error_code=getattr(rows, 'errno', None))
        raise rows
    candidates, seen = [], set()
    for family, kind, protocol, _, sockaddr in rows:
        if family not in (socket.AF_INET, socket.AF_INET6) or kind != socket.SOCK_DGRAM:
            continue
        if protocol not in (0, socket.IPPROTO_UDP):
            continue
        try:
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.version != (4 if family == socket.AF_INET else 6) or sockaddr[1] != endpoint[1]:
                continue
            key = family, str(ip), sockaddr[3] if family == socket.AF_INET6 else 0
        except (ValueError, IndexError, TypeError):
            continue
        if key in seen:
            continue
        seen.add(key)
        candidates.append((family, kind, protocol, '', sockaddr))
        diagnostic['candidates'].append({'family': socket.AddressFamily(family).name,
                                         'address': sockaddr[0], 'port': sockaddr[1]})
        if len(candidates) == MAX_DNS_CANDIDATES:
            break
    diagnostic['phase'] = 'COMPLETE' if candidates else 'NO_USABLE_ADDRESS'
    if not candidates:
        raise OSError('NTP_NO_USABLE_ADDRESS')
    return candidates


def _query_address(server, address, *, endpoint, deadline):
    packet = bytearray(48)
    packet[0] = 0x23
    with socket.socket(address[0], socket.SOCK_DGRAM) as sock:
        sock.settimeout(min(UDP_ATTEMPT_TIMEOUT_SECONDS, _remaining(deadline)))
        sock.connect(address[4])
        t1, m1 = time.time(), time.monotonic()
        packet[40:48] = stamp(t1)
        sock.settimeout(min(UDP_ATTEMPT_TIMEOUT_SECONDS, _remaining(deadline)))
        sock.send(packet)
        sock.settimeout(min(UDP_ATTEMPT_TIMEOUT_SECONDS, _remaining(deadline)))
        raw = sock.recv(512)
        t4, m4 = time.time(), time.monotonic()
    _remaining(deadline)
    if (len(raw) < 48 or raw[0] & 7 != 4 or raw[0] >> 6 == 3
            or not 1 <= raw[1] <= 15 or raw[24:32] != bytes(packet[40:48])):
        raise ValueError("NTP_PACKET_IDENTITY_OR_SYNC_INVALID")
    t2, t3 = decode(raw[32:40]), decode(raw[40:48])
    network = (t4 - t1) - (t3 - t2)
    jump = abs((t4 - t1) - (m4 - m1))
    if t3 < t2 or not 0 <= network <= 2 or jump > .05:
        raise ValueError("NTP_TIMESTAMPS_OR_WALL_JUMP_INVALID")
    offset = ((t2 - t1) + (t3 - t4)) / 2
    root_delay = struct.unpack("!i", raw[4:8])[0] / 65536
    dispersion = struct.unpack("!I", raw[8:12])[0] / 65536
    precision = 2 ** struct.unpack("!b", raw[3:4])[0]
    radius = network / 2 + max(0, root_delay) / 2 + dispersion + precision + jump + .002
    value = {"server": server, "address": address[4][0], "t1": t1, "t2": t2, "t3": t3, "t4": t4,
             "monotonic_elapsed_seconds": m4 - m1, "offset_seconds": offset,
             "uncertainty_radius_seconds": radius, "packet_hex": raw.hex(),
             "checked_at": datetime.fromtimestamp(t4, UTC).isoformat(), "udp_authenticated": False}
    if endpoint is not None:
        value['test_only_transport']=True
    return value


def query(server, *, endpoint=None, deadline=None):
    if server not in METHOD['servers']:
        raise ValueError('NTP_SERVER_NOT_LISTED')
    if endpoint is not None and (not isinstance(endpoint, (list, tuple)) or len(endpoint) != 2
            or endpoint[0] != '127.0.0.1' or type(endpoint[1]) is not int
            or not 1024 <= endpoint[1] <= 65535):
        raise ValueError('TEST_ONLY_UDP_ENDPOINTS_INVALID')
    started = time.monotonic()
    deadline = min(started + PER_HOST_TIMEOUT_SECONDS,
                   deadline if deadline is not None else started + PER_HOST_TIMEOUT_SECONDS)
    diagnostic = {'phase': 'DNS', 'dns': {'phase': 'DNS', 'candidates': [],
                  'candidate_limit': MAX_DNS_CANDIDATES}, 'attempts': [],
                  'per_host_timeout_seconds': PER_HOST_TIMEOUT_SECONDS,
                  'selection': 'FIRST_VALID_PACKET_IN_DNS_ORDER'}
    try:
        candidates = _resolve_candidates(endpoint or (server, 123), deadline, diagnostic['dns'])
        last_error = None
        for index, address in enumerate(candidates):
            diagnostic['phase'] = 'NETWORK'
            # Share remaining time so one unreachable IP cannot consume all fallbacks.
            attempt_timeout = min(UDP_ATTEMPT_TIMEOUT_SECONDS,
                                  _remaining(deadline) / (len(candidates) - index))
            attempt_started = time.monotonic()
            attempt = dict(diagnostic['dns']['candidates'][index], phase='NETWORK',
                           timeout_seconds=attempt_timeout)
            diagnostic['attempts'].append(attempt)
            try:
                value = _query_address(server, address, endpoint=endpoint,
                                       deadline=min(deadline, attempt_started + attempt_timeout))
            except (OSError, ValueError) as exc:
                last_error = exc
                attempt.update(phase='NETWORK' if isinstance(exc, OSError) else 'PACKET',
                               error_type=type(exc).__name__, error_code=getattr(exc, 'errno', None))
                attempt['elapsed_seconds'] = max(0, time.monotonic() - attempt_started)
            else:
                attempt['phase'] = diagnostic['phase'] = 'COMPLETE'
                diagnostic['elapsed_seconds'] = max(0, time.monotonic() - started)
                attempt['elapsed_seconds'] = max(0, time.monotonic() - attempt_started)
                value['transport_diagnostic'] = diagnostic
                value['observation_hash'] = common.digest(value)
                return value
        diagnostic['phase'] = 'PACKET' if isinstance(last_error, ValueError) else 'NETWORK'
        raise last_error
    except (OSError, ValueError) as exc:
        if str(exc) == 'NTP_DEADLINE_EXCEEDED':
            diagnostic['phase'] = 'DEADLINE'
        diagnostic['elapsed_seconds'] = max(0, time.monotonic() - started)
        exc.transport_diagnostic = diagnostic
        raise


def accepted_method(proof, *, root, now):
    try:
        path = (Path(root) / proof["acceptance_path"]).resolve()
        if not path.is_relative_to(Path(root).resolve()):
            return False
        raw = path.read_bytes()
        from hashlib import sha256
        original = json.loads(raw)
        return (sha256(raw).hexdigest() == proof["acceptance_sha256"]
                and original.get("status") == "ACCEPTED" and original.get("accepted_by") == "OWNER"
                and original.get("method") == METHOD and original.get("method_hash") == common.digest(METHOD)
                and common.timestamp(original["accepted_at"]) <= now < common.timestamp(original["valid_until"]))
    except (KeyError, ValueError, TypeError, OSError):
        return False


def evaluate(samples, *, proof=None, root=None, now):
    samples = deepcopy(samples)
    source_counts = Counter(row['server'] for row in samples
                            if isinstance(row, dict) and isinstance(row.get('server'), str))
    valid = []
    for row in samples:
        try:
            packet = bytes.fromhex(row["packet_hex"])
            t1, t2, t3, t4 = (row[k] for k in ("t1", "t2", "t3", "t4"))
            elapsed = row["monotonic_elapsed_seconds"]
            network = (t4 - t1) - (t3 - t2)
            jump = abs((t4 - t1) - elapsed)
            radius = (network / 2 + max(0, struct.unpack("!i", packet[4:8])[0] / 65536) / 2
                      + struct.unpack("!I", packet[8:12])[0] / 65536
                      + 2 ** struct.unpack("!b", packet[3:4])[0] + jump + .002)
            if (row.get('test_only_transport') or row.get("server") not in METHOD["servers"]
                    or source_counts[row['server']] != 1
                    or row.get("observation_hash") != common.digest({k: v for k, v in row.items() if k != "observation_hash"})
                    or not 0 <= (now - common.timestamp(row["checked_at"])).total_seconds() <= 900
                    or not common.finite(row["offset_seconds"]) or not common.finite(row["uncertainty_radius_seconds"])
                    or row["uncertainty_radius_seconds"] < 0
                    or len(packet) < 48 or packet[0] & 7 != 4 or packet[0] >> 6 == 3
                    or not 1 <= packet[1] <= 15 or packet[24:32] != stamp(t1)
                    or decode(packet[32:40]) != t2 or decode(packet[40:48]) != t3
                    or row["checked_at"] != datetime.fromtimestamp(t4, UTC).isoformat()
                    or row["offset_seconds"] != ((t2 - t1) + (t3 - t4)) / 2
                    or row["uncertainty_radius_seconds"] != radius
                    or t3 < t2 or not 0 <= network <= 2 or jump > .05):
                continue
            valid.append(row)
        except (ValueError, KeyError, TypeError, struct.error, IndexError, OverflowError):
            continue
    lower = max((r["offset_seconds"] - r["uncertainty_radius_seconds"] for r in valid), default=0)
    upper = min((r["offset_seconds"] + r["uncertainty_radius_seconds"] for r in valid), default=0)
    uncertainty = max(abs(lower), abs(upper)) * 1000 if valid else None
    enough = len({r["server"] for r in valid}) >= METHOD["minimum_sources"]
    accepted = bool(proof and root and accepted_method(proof, root=root, now=now))
    verified = enough and lower <= upper and uncertainty <= 1000 and accepted
    result = {"state": "VERIFIED_BOUND" if verified else "MEASURED_UNVERIFIED" if valid else "MEASUREMENT_UNAVAILABLE",
              "precision_verified": verified, "uncertainty_ms": uncertainty if verified else None,
              "measured_interval_ms": [lower * 1000, upper * 1000] if valid else None,
              "checked_at": max((r["checked_at"] for r in valid), default=now.isoformat()),
              "samples": samples, "method": METHOD, "method_acceptance": proof,
              "method_accepted": accepted, "system_clock_modified": False}
    result["source_hash"] = common.digest(result)
    return result


def publish(value):
    with _lock:
        global _attachment
        global _published_time
        _attachment = deepcopy(value)
        _published_time = datetime.now(UTC), time.monotonic()


def snapshot():
    with _lock:
        value = deepcopy(_attachment)
        if _published_time is not None:
            wall, elapsed = _published_time
            jump = abs((datetime.now(UTC) - wall).total_seconds() - (time.monotonic() - elapsed))
            if jump > METHOD['maximum_wall_jump_ms']/1000:
                value.update(state="CLOCK_DISCONTINUITY", precision_verified=False, uncertainty_ms=None)
        if value.get('precision_verified'):
            try:
                age=(datetime.now(UTC)-common.timestamp(value['checked_at'])).total_seconds()
                if not 0<=age<=METHOD['max_age_seconds']:
                    value.update(state='CLOCK_MEASUREMENT_STALE',precision_verified=False,uncertainty_ms=None)
            except (KeyError,ValueError,TypeError):
                value.update(state='MEASUREMENT_UNAVAILABLE',precision_verified=False,uncertainty_ms=None)
        return value


def _safe_stderr(text):
    import os
    for name in ('LONGBRIDGE_APP_KEY', 'LONGBRIDGE_APP_SECRET', 'LONGBRIDGE_ACCESS_TOKEN'):
        secret = os.environ.get(name)
        if secret:
            text = text.replace(secret, '[REDACTED]')
    text = re.sub(r'(?i)(authorization\s*[:=]\s*|bearer\s+)\S+', r'\1[REDACTED]', text)
    text = re.sub(r'(https?://)[^\s/@]+:[^\s/@]+@', r'\1[REDACTED]@', text)
    return text[:8192]


class ClockAttachmentMonitor:
    """One bounded measurement child, polled by the existing source worker."""

    def __init__(self, root=None, *, code_root=None, data_root=None,
                 method_config_path=None, acceptance_root=None, udp_test_endpoints=None):
        self.code_root = Path(code_root) if code_root is not None else Path(__file__).resolve().parent.parent
        self.data_root = Path(data_root if data_root is not None else root)
        self.method_config_path = Path(method_config_path) if method_config_path is not None else (
            self.code_root / 'config/review_acceptances/clock_measurement_method.json')
        self.acceptance_root = Path(acceptance_root) if acceptance_root is not None else self.code_root
        self.root, self.child = self.data_root, None
        self.udp_test_endpoints = udp_test_endpoints
        self.next_check, self.started = 0.0, 0.0
        self.next_system_check = 0.0
        self.last_child = None

    def _publish_host_status(self, elapsed):
        if elapsed<self.next_system_check:
            return
        self.next_system_check=elapsed+60
        from .options_host_clock import SCHEMA, read_system_status
        status=read_system_status()
        target=self.data_root/'work/option_foundation/runtime/host-clock.json'
        try:
            target.parent.mkdir(parents=True,exist_ok=True)
            temporary=target.with_suffix('.tmp')
            temporary.write_text(json.dumps({'schema':SCHEMA,'status':status}),encoding='utf-8')
            temporary.replace(target)
        except OSError as exc:
            self.host_status_store_error=type(exc).__name__

    def _diagnostic(self, phase, *, stderr='', returncode=None, pid=None):
        return {'phase': phase, 'child_pid': pid, 'returncode': returncode,
                'cwd': str(self.code_root), 'interpreter': sys.executable,
                'data_root': str(self.data_root), 'method_config_path': str(self.method_config_path),
                'acceptance_root': str(self.acceptance_root), 'stderr': _safe_stderr(stderr),
                'stderr_truncated': len(stderr) > 8192,
                'elapsed_seconds': max(0, time.monotonic()-self.started),
                'test_only_transport': self.udp_test_endpoints is not None}

    def _store(self, value):
        directory = self.data_root / 'work/option_foundation/runtime'
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / 'clock-measurement.json'
        temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps(value, indent=2), encoding='utf-8')
        temp.replace(target)

    def _failure(self, reason, phase, diagnostic):
        value = {'state': 'MEASUREMENT_UNAVAILABLE', 'precision_verified': False,
                 'reason': reason, 'error_phase': phase, 'child_diagnostic': diagnostic,
                 'system_clock_modified': False}
        try:
            self._store(value)
        except OSError as exc:
            value['store_error_type'] = type(exc).__name__
        publish(value)

    def tick(self, now):
        elapsed = time.monotonic()
        self._publish_host_status(elapsed)
        if self.child is not None:
            if self.child.poll() is None and elapsed - self.started > 6:
                pid = self.child.pid
                self.child.kill()
                _, stderr = self.child.communicate(timeout=1)
                diagnostic = self._diagnostic('NETWORK_OR_CHILD_TIMEOUT', stderr=stderr,
                                              returncode=self.child.returncode, pid=pid)
                self.child = None
                self.last_child = diagnostic
                self._failure('MEASUREMENT_PROCESS_TIMEOUT', 'NETWORK_OR_CHILD_TIMEOUT', diagnostic)
            elif self.child.poll() is not None:
                pid, returncode = self.child.pid, self.child.returncode
                out, stderr = self.child.communicate(timeout=1)
                self.child = None
                phase = 'IMPORT' if 'ModuleNotFoundError' in stderr else 'CHILD_EXIT'
                diagnostic = self._diagnostic(phase, stderr=stderr, returncode=returncode, pid=pid)
                self.last_child = diagnostic
                if returncode:
                    self._failure('MEASUREMENT_CHILD_FAILED', phase, diagnostic)
                    return snapshot()
                phase = 'JSON'
                try:
                    if len(out) > 32768:
                        raise ValueError('MEASUREMENT_JSON_BOUND_EXCEEDED')
                    samples = json.loads(out)
                    if not isinstance(samples, list) or len(samples) > len(METHOD['servers']):
                        raise ValueError('MEASUREMENT_SAMPLE_SCHEMA_INVALID')
                    phase = 'METHOD'
                    proof_file = self.method_config_path
                    proof = json.loads(proof_file.read_text(encoding='utf-8')) if proof_file.exists() else None
                    value = evaluate(samples, proof=proof, root=self.acceptance_root, now=now)
                    if self.udp_test_endpoints is not None:
                        value.update(test_only=True,precision_verified=False,uncertainty_ms=None,
                                     state='MEASURED_UNVERIFIED')
                    diagnostic['phase'] = 'COMPLETE'
                    value['child_diagnostic'] = diagnostic
                    value['method_config_state'] = 'PRESENT' if proof_file.exists() else 'MISSING'
                    if not any('observation_hash' in row for row in samples):
                        value['error_phase'] = 'NETWORK_OR_PACKET'
                    value['source_hash'] = common.digest({k:v for k,v in value.items() if k!='source_hash'})
                    phase = 'STORE'
                    self._store(value)
                    publish(value)
                except (ValueError, OSError, TypeError) as exc:
                    diagnostic['error_type'] = type(exc).__name__
                    self._failure('MEASUREMENT_'+phase+'_FAILED', phase, diagnostic)
        if self.child is None and elapsed >= self.next_check:
            self.next_check = elapsed + 300
            self.started = elapsed
            flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            arguments = [sys.executable, '-m', 'kquant.options_clock_measurement']
            if self.udp_test_endpoints is not None:
                arguments += ['--test-only-udp-endpoints', json.dumps(self.udp_test_endpoints)]
            try:
                self.child = subprocess.Popen(arguments, cwd=self.code_root,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    encoding='utf-8', errors='replace', creationflags=flags)
            except OSError as exc:
                diagnostic = self._diagnostic('SPAWN', stderr=str(exc))
                diagnostic['error_type'] = type(exc).__name__
                self.last_child = diagnostic
                self._failure('MEASUREMENT_SPAWN_FAILED', 'SPAWN', diagnostic)
        return snapshot()

    def close(self):
        if self.child is not None:
            if self.child.poll() is None:
                self.child.kill()
            self.child.communicate(timeout=1)
            self.child = None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--test-only-udp-endpoints')
    args = parser.parse_args()
    endpoints = json.loads(args.test_only_udp_endpoints) if args.test_only_udp_endpoints else None
    if endpoints is not None:
        if (not isinstance(endpoints, dict) or set(endpoints)!=set(METHOD['servers'])
                or any(not isinstance(row,list) or len(row)!=2 or row[0]!='127.0.0.1'
                       or type(row[1]) is not int or not 1024<=row[1]<=65535 for row in endpoints.values())):
            raise ValueError('TEST_ONLY_UDP_ENDPOINTS_INVALID')
    observations = []
    deadline = time.monotonic() + CHILD_TOTAL_TIMEOUT_SECONDS
    for host in METHOD["servers"]:
        print(json.dumps({'phase':'NETWORK','server':host}), file=sys.stderr, flush=True)
        try:
            observations.append(query(host, endpoint=endpoints.get(host) if endpoints else None,
                                      deadline=deadline))
        except (OSError, ValueError) as exc:
            row = {'server':host, 'error_type':type(exc).__name__,
                                 'phase':'NETWORK' if isinstance(exc,OSError) else 'PACKET',
                                 'error_code':getattr(exc,'errno',None)}
            if hasattr(exc, 'transport_diagnostic'):
                row['transport_diagnostic'] = exc.transport_diagnostic
            if endpoints is not None:
                row['test_only_transport'] = True
            observations.append(row)
    print(json.dumps({'phase':'ENCODE','sample_count':len(observations)}),file=sys.stderr,flush=True)
    print(json.dumps(observations))
