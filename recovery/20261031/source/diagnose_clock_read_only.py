"""Independent clock diagnostics only. No SDK, .env, time changes or publication.

Additional hosts help diagnose a bias; they NEVER replace the project's fixed
two-source METHOD or manufacture its required OWNER method acceptance.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
from pathlib import Path
import socket
import ssl
import struct
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent
UTC = timezone.utc
EPOCH = 2208988800
FIXED_SERVERS = ["time.cloudflare.com", "time.windows.com"]


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def stamp(value):
    value += EPOCH
    return struct.pack("!II", int(value), int(value % 1 * 2 ** 32))


def decode(value):
    seconds, fraction = struct.unpack("!II", value)
    return seconds - EPOCH + fraction / 2 ** 32


def sample_address(server, address):
    packet = bytearray(48)
    packet[0] = 0x23
    base = {"server": server, "address": address[4][0],
            "address_family": "IPv4" if address[0] == socket.AF_INET else "IPv6",
            "fixed_method_source": server in FIXED_SERVERS,
            "udp_authenticated": False, "timeout_seconds": 1}
    try:
        with socket.socket(address[0], socket.SOCK_DGRAM) as sock:
            sock.settimeout(1)
            sock.connect(address[4])
            t1, m1 = time.time(), time.monotonic()
            packet[40:48] = stamp(t1)
            sock.send(packet)
            raw = sock.recv(512)
            t4, m4 = time.time(), time.monotonic()
        if (len(raw) < 48 or raw[0] & 7 != 4 or raw[0] >> 6 == 3
                or not 1 <= raw[1] <= 15 or raw[24:32] != bytes(packet[40:48])):
            raise ValueError("NTP_PACKET_IDENTITY_OR_SYNC_INVALID")
        t2, t3 = decode(raw[32:40]), decode(raw[40:48])
        elapsed = m4 - m1
        jump = abs((t4 - t1) - elapsed)
        network = (t4 - t1) - (t3 - t2)
        if t3 < t2 or not 0 <= network <= 2 or jump > .05:
            raise ValueError("NTP_TIMESTAMPS_OR_WALL_JUMP_INVALID")
        root_delay = struct.unpack("!i", raw[4:8])[0] / 65536
        dispersion = struct.unpack("!I", raw[8:12])[0] / 65536
        precision = 2 ** struct.unpack("!b", raw[3:4])[0]
        radius = network / 2 + max(0, root_delay) / 2 + dispersion + precision + jump + .002
        offset = ((t2 - t1) + (t3 - t4)) / 2
        base.update(status="MEASURED_DIAGNOSTIC_ONLY", t1=t1, t2=t2, t3=t3, t4=t4,
                    offset_server_minus_local_seconds=offset,
                    uncertainty_radius_seconds=radius,
                    local_ahead_interval_seconds=[-offset - radius, -offset + radius],
                    monotonic_elapsed_seconds=elapsed, wall_jump_seconds=jump,
                    packet_hex=raw.hex(), trust_assumption="SERVER_ACCURATE_AND_NO_UDP_SPOOFING")
    except (OSError, ValueError) as exc:
        base.update(status="UNAVAILABLE", error_type=type(exc).__name__)
        if isinstance(exc, OSError) and getattr(exc, "winerror", None) is not None:
            base["windows_error_code"] = exc.winerror
        if isinstance(exc, ValueError):
            base["validation_error"] = str(exc)
    base["sha256"] = hashlib.sha256(canonical(base)).hexdigest()
    return base


def ntp_source(server):
    try:
        addresses = socket.getaddrinfo(server, 123, type=socket.SOCK_DGRAM)
        # Exactly one diagnostic address from each available family; DNS order
        # and the original first address are recorded to expose route failures.
        selected = []
        for family in (socket.AF_INET, socket.AF_INET6):
            address = next((item for item in addresses if item[0] == family), None)
            if address is not None:
                selected.append(address)
        return {"server": server, "dns_first_address": addresses[0][4][0] if addresses else None,
                "dns_addresses": sorted({item[4][0] for item in addresses}),
                "samples": [sample_address(server, item) for item in selected]}
    except OSError as exc:
        return {"server": server, "status": "DNS_UNAVAILABLE", "error_type": type(exc).__name__}


def https_source(label, url, trace=False):
    nonce = uuid.uuid4().hex
    url += ("&" if "?" in url else "?") + "clock_probe=" + nonce
    base = {"source": label, "endpoint": url.split("?")[0], "nonce": nonce,
            "transport": "HTTPS_TLS_CERTIFICATE_VALIDATED", "fixed_method_source": False,
            "request_cache_control": "no-cache, no-store", "response_body_saved": False,
            "credentials_sent": False, "maximum_response_bytes": 16384}
    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache, no-store",
                                                   "Pragma": "no-cache",
                                                   "User-Agent": "KQUANT-ReadOnlyClockDiagnostic/1.0"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    t1, m1 = time.time(), time.monotonic()
    try:
        with opener.open(request, timeout=5) as response:
            headers = {name: response.headers.get(name) for name in
                       ("Date", "Age", "Cache-Control", "Expires", "Via", "X-Cache", "CF-Cache-Status")}
            # The Cloudflare trace includes requester IP: only its numeric ts
            # field may be preserved; the body and all other fields are discarded.
            body = response.read(16384) if trace else b""
            status = response.status
        t4, m4 = time.time(), time.monotonic()
        base.update(status="MEASURED_DIAGNOSTIC_ONLY", http_status=status,
                    allowed_headers=headers, t1=t1, t4=t4, monotonic_elapsed_seconds=m4 - m1,
                    wall_jump_seconds=abs((t4 - t1) - (m4 - m1)))
        date_value = headers.get("Date")
        if date_value:
            unix = parsedate_to_datetime(date_value).timestamp()
            base["http_date_unix"] = unix
            base["http_date_granularity_seconds"] = 1
            base["fresh_date_conditional_local_ahead_interval_seconds"] = [t1 - unix - 1, t4 - unix]
        age = headers.get("Age")
        cache = (headers.get("X-Cache") or "") + " " + (headers.get("CF-Cache-Status") or "")
        cached = (age is not None and age.isdigit() and int(age) > 0) or "HIT" in cache.upper()
        base["cache_assessment"] = "CACHED_RESPONSE_NOT_CLOCK_EVIDENCE" if cached else "NO_CACHE_HIT_MARKER_FRESHNESS_NOT_GUARANTEED"
        if trace:
            lines = body.decode("ascii", errors="ignore").splitlines()
            value = next((line.partition("=")[2] for line in lines if line.startswith("ts=")), "")
            if value and all(char in "0123456789." for char in value):
                unix = float(value)
                if 1_700_000_000 <= unix <= 2_000_000_000:
                    base["trace_server_unix"] = unix
                    base["trace_server_unix_text"] = value
                    # Trailing .000 is formatting, not proof of millisecond
                    # resolution. Its generation semantics are not documented
                    # here, so use at least one second on each end regardless
                    # of its represented number of digits.
                    textual_resolution = 10 ** -len(value.partition(".")[2]) if "." in value else 1.0
                    granularity = max(1.0, textual_resolution)
                    base["trace_timestamp_textual_resolution_seconds"] = textual_resolution
                    base["trace_timestamp_granularity_seconds"] = granularity
                    base["fresh_trace_conditional_local_ahead_interval_seconds"] = [t1 - unix - granularity, t4 - unix + granularity]
                    base["trace_http_date_delta_seconds"] = unix - base.get("http_date_unix", unix)
        base["trust_assumption"] = "DOMAIN_TLS_AUTHENTICATED_SERVER_CLOCK_AND_RESPONSE_FRESHNESS_NOT_INDEPENDENTLY_GUARANTEED"
    except Exception as exc:
        base.update(status="UNAVAILABLE", error_type=type(exc).__name__)
    base["sha256"] = hashlib.sha256(canonical(base)).hexdigest()
    return base


def windows_source():
    script = r"""
    $svc = Get-Service -Name W32Time
    $system = Get-CimInstance Win32_ComputerSystem
    $parameters = Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Services\W32Time\Parameters'
    $ntpClient = Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Services\W32Time\TimeProviders\NtpClient'
    $vm = Get-ItemProperty -LiteralPath 'HKLM:\SYSTEM\CurrentControlSet\Services\W32Time\TimeProviders\VMICTimeProvider' -ErrorAction SilentlyContinue
    $rawStatus = & w32tm /query /status /verbose 2>&1 | Out-String
    $statusExit = $LASTEXITCODE
    $rawSource = & w32tm /query /source 2>&1 | Out-String
    $sourceExit = $LASTEXITCODE
    $codePattern = '0x[0-9a-fA-F]{8}'
    $result = [ordered]@{
      service_name = $svc.Name; service_status = $svc.Status.ToString(); service_start_type = $svc.StartType.ToString()
      part_of_domain = $system.PartOfDomain; hypervisor_present = $system.HypervisorPresent
      clock_type = $parameters.Type; configured_ntp_server = $parameters.NtpServer
      ntp_client_enabled = $ntpClient.Enabled; vm_time_provider_enabled = $vm.Enabled
      w32tm_status_exit = $statusExit; w32tm_source_exit = $sourceExit
      w32tm_status_error_codes = @([regex]::Matches($rawStatus,$codePattern) | ForEach-Object {$_.Value})
      w32tm_source_error_codes = @([regex]::Matches($rawSource,$codePattern) | ForEach-Object {$_.Value})
      timezone_id = [TimeZoneInfo]::Local.Id; observed_local_utc = [DateTime]::UtcNow.ToString('o')
    }
    [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
    $result | ConvertTo-Json -Compress
    """
    try:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        result = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, timeout=6, creationflags=flags)
        return json.loads(result.stdout.decode("utf-8"))
    except Exception as exc:
        return {"status": "UNAVAILABLE", "error_type": type(exc).__name__}


def worker():
    started = time.monotonic()
    tasks = [("windows", windows_source),
             ("ntp_cloudflare", lambda: ntp_source("time.cloudflare.com")),
             ("ntp_windows", lambda: ntp_source("time.windows.com")),
             ("ntp_google", lambda: ntp_source("time.google.com")),
             ("ntp_apple", lambda: ntp_source("time.apple.com")),
             ("https_cloudflare", lambda: https_source("Cloudflare trace", "https://www.cloudflare.com/cdn-cgi/trace", True)),
             ("https_google", lambda: https_source("Google 204", "https://www.google.com/generate_204")),
             ("https_microsoft", lambda: https_source("Microsoft home", "https://www.microsoft.com/"))]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [(name, pool.submit(call)) for name, call in tasks]
        observations = {name: future.result() for name, future in futures}
    evidence = {"record_kind": "INDEPENDENT_READ_ONLY_CLOCK_DIAGNOSIS", "created_at_local_utc": datetime.now(UTC).isoformat(),
                "elapsed_monotonic_seconds": time.monotonic() - started,
                "observations": observations, "fixed_method_servers_preserved": FIXED_SERVERS,
                "production_clock_precision_verified": False, "owner_acceptance_created": False,
                "system_clock_modified": False, "service_configuration_modified": False,
                "sdk_used": False, "env_file_read": False, "published": False,
                "diagnostic_schema_version": 2,
                "interpretation": {"offset_sign": "negative server-minus-local means local wall clock ahead",
                                   "extra_sources": "DIAGNOSTIC_ONLY_NOT_FIXED_METHOD_SUBSTITUTES",
                                   "http_date": "integer-second and possibly cached; conditional intervals only",
                                   "ntp": "unauthenticated UDP; packet correlation cannot exclude spoofing"}}
    raw = canonical(evidence)
    digest = hashlib.sha256(raw).hexdigest()
    directory = ROOT / "evidence"
    directory.mkdir(exist_ok=True)
    name = datetime.now(UTC).strftime("clock-diagnosis-%Y%m%dT%H%M%S%fZ-") + digest + ".json"
    path = directory / name
    with path.open("xb") as stream:
        stream.write(raw)
    print(json.dumps({"receipt": str(path), "sha256": digest,
                      "elapsed_monotonic_seconds": evidence["elapsed_monotonic_seconds"],
                      "service": observations["windows"],
                      "ntp": {name: [{key: sample.get(key) for key in
                                      ("server", "address_family", "status", "error_type",
                                       "offset_server_minus_local_seconds", "uncertainty_radius_seconds")}
                                     for sample in item.get("samples", [])]
                              for name, item in observations.items() if name.startswith("ntp_")},
                      "https": {name: {key: item.get(key) for key in
                                        ("status", "error_type", "http_date_unix", "trace_server_unix",
                                         "cache_assessment", "fresh_trace_conditional_local_ahead_interval_seconds",
                                         "fresh_date_conditional_local_ahead_interval_seconds")}
                                for name, item in observations.items() if name.startswith("https_")}}))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        worker()
    else:
        # DNS can block independently of UDP/HTTPS timeouts. The parent bounds
        # the entire child and deliberately makes no qualified attachment.
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        try:
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker"],
                                    capture_output=True, timeout=30, creationflags=flags)
            if result.returncode:
                print(json.dumps({"status": "DIAGNOSTIC_CHILD_FAILED", "exit_code": result.returncode}))
                raise SystemExit(1)
            print(result.stdout.decode("utf-8"), end="")
        except subprocess.TimeoutExpired:
            print(json.dumps({"status": "DIAGNOSTIC_PARENT_TIMEOUT", "timeout_seconds": 30}))
            raise SystemExit(1)
